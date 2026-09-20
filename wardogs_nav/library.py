"""Portable road libraries and exact-path favourites, using the shared road graph."""
from copy import deepcopy
import math
from .model import uid, KINDS, validate_project
from .routing import (Route, RouteError, distance, project, bearing, angle_delta,
                      blocked, cumulative, point_at, nearest_on_route, plan,
                      build_graph, junctions_on_route, usable, bridge_ports, roads_connect)


def route_metadata(route):
    result={'road_ids':list(route.road_ids)}
    if route.bridges:
        result.update(bridges=list(route.bridges),bridge_connections=deepcopy(route.bridge_connections))
    return result


def saved_route(name, route, *, snap_to_roads=False, build_roads=True):
    return dict(id=uid(), name=name, points=[list(p) for p in route.points], kinds=list(route.kinds),
                snap_to_roads=bool(snap_to_roads),build_roads=bool(build_roads),**route_metadata(route))


def snap_saved(roads,saved,policy,avoid=(),max_snap=80.):
    """Resolve rough control points through the production road graph once.

    The stored result is the complete path, never just its controls. Dense
    legacy paths are simplified into matching controls; both those controls
    and the complete resolved path are retained for later exports/imports.
    """
    controls=deepcopy(saved.get('control_points',saved['points']))
    guides=controls
    if 'control_points' not in saved and len(controls)>2:
        import cv2,numpy as np
        guides=cv2.approxPolyDP(np.float32(controls),2.,False)[:,0].tolist()
    try:route=plan(roads,guides,policy['allowed'],policy['confirmed_only'],avoid,max_snap=max_snap,preferences=policy.get('preferences'))
    except RouteError as error:raise RouteError('无法贴合道路：'+str(error)) from error
    result=deepcopy(saved)
    result.update(points=[list(p) for p in route.points],kinds=list(route.kinds),
                  control_points=deepcopy(guides),snap_to_roads=True,build_roads=False,**route_metadata(route))
    return result


class RoadIndex:
    def __init__(self, roads):
        self.cells={}
        for road in roads:self.add(road)

    def add(self, road):
        for a,b in zip(road['points'],road['points'][1:]):
            if distance(a,b)<.01:continue
            for x in range(math.floor((min(a[0],b[0])-1.6)/24),math.floor((max(a[0],b[0])+1.6)/24)+1):
                for y in range(math.floor((min(a[1],b[1])-1.6)/24),math.floor((max(a[1],b[1])+1.6)/24)+1):
                    self.cells.setdefault((x,y),[]).append((a,b,road))

    def covering(self, a, b, preferred=None, bridge=None, road_id=None):
        mid=[(a[k]+b[k])/2 for k in (0,1)]
        options=[]
        for c,d,road in self.cells.get((math.floor(mid[0]/24),math.floor(mid[1]/24)),[]):
            gap=project(mid,c,d)[0]
            angle=abs(angle_delta(bearing(a,b),bearing(c,d)))
            if gap<=1.5 and min(angle,180-angle)<35:
                # An edited road keeps its identity: its current bridge flags
                # override a favourite's older snapshot, rather than cloning it.
                same=road['id']==road_id
                if not same and bridge is not None and bool(road.get('bridge'))!=bridge:continue
                if bridge is not None and max(project(a,c,d)[0],project(b,c,d)[0])>1.5:continue
                options.append((not same,road['kind']!=preferred,gap,road))
        return min(options,key=lambda item:item[:3])[3] if options else None


def sampled(saved, step=2.):
    """Retain every original vertex; split long edges to find interior gaps."""
    points=[list(saved['points'][0])];kinds=[];bridges=[];ids=[]
    for index,(a,b,kind) in enumerate(zip(saved['points'],saved['points'][1:],saved['kinds'])):
        length=distance(a,b)
        if length<.01:continue
        n=max(1,math.ceil(length/step))
        for i in range(1,n+1):
            points.append([a[k]+(b[k]-a[k])*i/n for k in (0,1)])
            kinds.append(kind)
            bridges.append(saved['bridges'][index] if 'bridges' in saved else None)
            ids.append(saved['road_ids'][index] if 'road_ids' in saved else None)
    return points,kinds,bridges,ids


def supplement_roads(roads, saved):
    """Add only uncovered spans. Repeated load/import is idempotent."""
    index=RoadIndex(roads);points,kinds,bridges,ids=sampled(saved)
    ports=saved.get('bridge_connections',[])
    additions=[];run=[];run_kind=None;run_bridge=False
    def flush():
        nonlocal run,run_kind
        if len(run)>=2:
            # Drop exactly collinear intermediate samples without cutting bends.
            simple=[run[0]]
            for i in range(1,len(run)-1):
                if project(run[i],simple[-1],run[i+1])[0]>.02:simple.append(run[i])
            simple.append(run[-1])
            for i in range(0,len(simple)-1,1999):
                road=dict(id=uid(),name=f"收藏补路 · {saved['name']}",kind=run_kind,
                          confirmed=True,points=simple[i:i+2000],note='由完整收藏路径补入')
                if run_bridge:
                    road.update(bridge=True,bridge_start=any(distance(road['points'][0],p)<1.5 for p in ports),
                                bridge_end=any(distance(road['points'][-1],p)<1.5 for p in ports))
                additions.append(road);index.add(road)
        run=[];run_kind=None
    previous_covered=False;previous_bridge=False
    for i,(a,b,kind,bridge,road_id) in enumerate(zip(points,points[1:],kinds,bridges,ids)):
        if run and run_bridge and any(distance(a,p)<1.5 for p in ports):flush()
        covered=index.covering(a,b,kind,bridge,road_id)
        if covered:
            if run and not run_bridge and not covered.get('bridge'):run.append(b)
            flush();previous_covered=True;previous_bridge=bool(covered.get('bridge'));continue
        if run and (kind!=run_kind or bool(bridge)!=run_bridge):flush()
        if not run:
            run_bridge=bool(bridge)
            run=([points[i-1],a] if previous_covered and i and not run_bridge and not previous_bridge else [a]);run_kind=kind
        run.append(b)
        previous_covered=False
    flush()
    roads.extend(additions)
    return len(additions)


def slice_route(route, start, end):
    lengths=cumulative(route.points)
    start=max(0.,start);end=min(route.length,end)
    points=[point_at(route.points,lengths,start)];kinds=[];ids=[];bridges=[]
    for i in range(len(route.points)-1):
        lo=max(start,lengths[i]);hi=min(end,lengths[i+1])
        if hi-lo<1e-6:continue
        points.append(point_at(route.points,lengths,hi));kinds.append(route.kinds[i]);ids.append(route.road_ids[i])
        if route.bridges:bridges.append(route.bridges[i])
    return Route(points,kinds,ids,max(0,end-start),list(route.snap_distances),route.unconfirmed,
                 [dict(j,at=j['at']-start) for j in route.junctions if start<j['at']<end],bridges,deepcopy(route.bridge_connections))


def join_routes(parts):
    parts=[p for p in parts if len(p.points)>1 and p.length>1e-6]
    if not parts:raise RouteError('起终点太近，请选择更远的路径')
    points=list(parts[0].points);kinds=list(parts[0].kinds);ids=list(parts[0].road_ids)
    bridges=list(parts[0].bridges or [False]*len(parts[0].kinds));ports=deepcopy(parts[0].bridge_connections)
    junctions=list(parts[0].junctions);length=parts[0].length
    for part in parts[1:]:
        if distance(points[-1],part.points[0])>1.6:
            raise RouteError('收藏路线连接处不连续，请补画连接道路')
        # Graph nodes may be merged within 1.5 px; retain the exact shared join.
        points.extend(part.points[1:]);kinds.extend(part.kinds);ids.extend(part.road_ids)
        bridges.extend(part.bridges or [False]*len(part.kinds));ports.extend(deepcopy(part.bridge_connections))
        junctions.extend(dict(j,at=j['at']+length) for j in part.junctions)
        length+=part.length
    return Route(points,kinds,ids,cumulative(points)[-1],
                 parts[0].snap_distances, max(p.unconfirmed for p in parts),junctions,bridges,ports)


def follow_saved(roads, saved, policy, avoid=(), start=None, reverse=False, minimum_progress=0.):
    if not saved.get('build_roads',True):
        # These spans belong to this journey only. Normal planning and exported
        # public road libraries must not acquire them on load, replan or return.
        roads=list(roads)
        supplement_roads(roads,saved)
    points,kinds,bridges,ids=sampled(saved)
    if reverse:points.reverse();kinds.reverse();bridges.reverse();ids.reverse()
    if len(points)<2:raise RouteError('收藏路线长度不足')
    index=RoadIndex(roads);owners=[]
    ports=[p for road in roads for p in bridge_ports(road)]
    for a,b,kind,bridge,road_id in zip(points,points[1:],kinds,bridges,ids):
        road=index.covering(a,b,kind,bridge,road_id)
        if road is None:raise RouteError('收藏路径有缺路，请重新载入收藏以补路')
        if not usable(road,policy['allowed'],policy['confirmed_only']):
            raise RouteError(f"收藏经过未允许的路段：{KINDS[road['kind']]}。请调整规则或编辑收藏")
        if owners and not roads_connect(owners[-1],road,a,ports):
            raise RouteError('收藏在桥面与地面交叉处换层，不能直接转弯；请经真实桥头重新规划收藏')
        owners.append(road)
    route=Route(points,[r['kind'] for r in owners],[r['id'] for r in owners],
                cumulative(points)[-1],[0,0],0,bridges=[bool(r.get('bridge')) for r in owners],
                bridge_connections=[list(p) for r in {r['id']:r for r in owners}.values() for p in bridge_ports(r)])
    nodes,adj,_,_=build_graph(roads,[points[0],points[-1]],set(KINDS),max_snap=2.,anchor_roads=[owners[0]['id'],owners[-1]['id']])
    route.junctions=junctions_on_route(nodes,adj,route)
    # Join the closest *remaining* part of the saved path. Never shortcut its rest.
    connector=None
    if start is not None:
        projection=nearest_on_route(start,route.points,minimum_progress)
        if projection is None:raise RouteError('无法接入收藏路线')
        gap,s,segment,q=projection
        if gap>1.5:
            connector=plan(roads,[start,q],policy['allowed'],policy['confirmed_only'],avoid,preferences=policy.get('preferences'),anchor_roads=[None,route.road_ids[segment]])
        route=slice_route(route,s,route.length)
        if route.length<1:raise RouteError('已在收藏路线终点附近；可反向载入')
    if any(blocked(p,p,z) for p in (route.points[0],route.points[-1]) for z in avoid):
        raise RouteError('收藏起终点位于危险区内，请调整危险区或收藏')
    lengths=cumulative(route.points)
    bad=[i for i,(a,b) in enumerate(zip(route.points,route.points[1:])) if any(blocked(a,b,z) for z in avoid)]
    if bad:
        # Leave/rejoin at actual junctions, keeping all unaffected saved sections.
        exits=[0.,*(j['at'] for j in route.junctions),route.length]
        spans=[]
        for i in bad:
            if spans and i==spans[-1][1]+1:spans[-1][1]=i
            else:spans.append([i,i])
        parts=[];cursor=0.
        for first,last in spans:
            if lengths[last+1]<=cursor:continue
            before=[s for s in reversed(exits) if cursor<=s<lengths[first]]
            after=[s for s in exits if s>lengths[last+1]]
            detour=None
            for radius in range(max(len(before),len(after))):
                if not before or not after:break
                a=before[min(radius,len(before)-1)];b=after[min(radius,len(after)-1)]
                try:
                    from bisect import bisect_right
                    hints=[route.road_ids[min(len(route.road_ids)-1,bisect_right(lengths,s)-1)] for s in (a,b)]
                    detour=plan(roads,[point_at(route.points,lengths,a),point_at(route.points,lengths,b)],
                                policy['allowed'],policy['confirmed_only'],avoid,max_snap=2.,preferences=policy.get('preferences'),anchor_roads=hints)
                    break
                except RouteError:continue
            if detour is None:raise RouteError('危险区截断了收藏路径，附近没有符合规则的绕行道路')
            parts.extend([slice_route(route,cursor,a),detour]);cursor=b
        parts.append(slice_route(route,cursor,route.length));route=join_routes(parts)
    if connector:route=join_routes([connector,route])
    route.junctions=junctions_on_route(nodes,adj,route)
    if any(blocked(a,b,z) for a,b in zip(route.points,route.points[1:]) for z in avoid):
        raise RouteError('收藏路径仍与危险区相交，请调整危险区或补画绕行道路')
    route.unconfirmed=0
    return route


def library_payload(project_data, kind):
    payload=dict(schema=1,map=project_data['map'],library=kind,meters_per_pixel=project_data.get('meters_per_pixel'),
                 roads=[],notes=deepcopy(project_data['notes']),avoid=[],waypoints=[],destinations=[],
                 destination=None,roundtrip=False,route_library=[])
    if kind=='roads':payload['roads']=deepcopy(project_data['roads'])
    elif kind=='routes':
        payload['route_library']=deepcopy(project_data.get('route_library',[]))
        for saved in payload['route_library']:
            saved.setdefault('snap_to_roads',False);saved.setdefault('build_roads',True)
            if any(r.get('bridge') for r in project_data['roads']):
                # Refresh old favourites after a road has been marked as a
                # bridge. Export actual layers, not an obsolete ground copy.
                resolved=follow_saved(project_data['roads'],saved,project_data['policy'])
                if any(resolved.bridges):
                    original={tuple(p) for p in saved['points']};keep=[0]
                    for i,p in enumerate(resolved.points[1:-1],1):
                        if (tuple(p) in original or resolved.road_ids[i-1]!=resolved.road_ids[i]
                                or resolved.bridges[i-1]!=resolved.bridges[i]
                                or project(p,resolved.points[i-1],resolved.points[i+1])[0]>1e-6):keep.append(i)
                    keep.append(len(resolved.points)-1)
                    saved.update(points=[list(resolved.points[i]) for i in keep],
                                 kinds=[resolved.kinds[i] for i in keep[:-1]],
                                 road_ids=[resolved.road_ids[i] for i in keep[:-1]],
                                 bridges=[resolved.bridges[i] for i in keep[:-1]],
                                 bridge_connections=deepcopy(resolved.bridge_connections))
    else:raise ValueError('未知资料库类型')
    return validate_project(payload)


def check_library_target(current,incoming,kind):
    if incoming['map']!=current['map']:
        raise ValueError(f"资料库属于 {incoming['map'].upper()}，请先切换到对应地图再导入")
    if incoming.get('library',kind)!=kind:raise ValueError('文件类型不符，请使用对应的道路或收藏导入按钮')


def merge_library(current, incoming, kind, *, snap_to_roads=None, build_roads=None):
    incoming=validate_project(incoming);check_library_target(current,incoming,kind)
    result=deepcopy(current)
    key='roads' if kind=='roads' else 'route_library'
    added=0;new_routes=[]
    for collection in (key,'notes'):
        target=result.setdefault(collection,[])
        for value in incoming[collection]:
            value=deepcopy(value)
            if collection=='route_library':
                if snap_to_roads:
                    value=snap_saved(current['roads'],value,current['policy'],current['avoid'])
                else:
                    # Keeping a file's exact path also keeps its creation
                    # metadata. "Do not re-match" does not undo prior matching.
                    if snap_to_roads is not None:value.setdefault('snap_to_roads',False)
                    if build_roads is not None:value['build_roads']=bool(build_roads)
            def equivalent(item):
                ignored={'id'}
                if collection=='roads':
                    ignored.update(k for k in ('bridge','bridge_start','bridge_end') if item.get(k) is False)
                return {k:v for k,v in item.items() if k not in ignored}
            existing=next((v for v in target if equivalent(v)==equivalent(value)),None)
            if existing is not None:
                if collection=='route_library':new_routes.append(existing)
                continue
            if any(v['id']==value['id'] for v in target):value['id']=uid()
            target.append(value)
            if collection=='route_library':new_routes.append(value)
            if collection==key:added+=1
    supplemented=0
    if kind=='routes':
        for saved in new_routes:
            if saved.get('build_roads',True):supplemented+=supplement_roads(result['roads'],saved)
    return validate_project(result),added,supplemented
