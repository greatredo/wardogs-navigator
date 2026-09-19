"""Polyline graph routing with explicit road types and exclusion circles."""
from __future__ import annotations
from dataclasses import dataclass, field
import heapq
import math


def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])


def project(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy) / max(dx*dx+dy*dy, 1e-12)))
    q = (a[0]+t*dx, a[1]+t*dy)
    return distance(p, q), q, t


def bearing(a, b):
    return math.degrees(math.atan2(b[0]-a[0], a[1]-b[1])) % 360


def angle_delta(a, b):
    return (b-a+180) % 360 - 180


def blocked(a, b, zone):
    if zone.get('shape') != 'rect':
        return project(zone['point'], a, b)[0] <= zone['radius']
    x,y=zone['point'];hw=zone['width']/2;hh=zone['height']/2
    # Liang-Barsky segment / rectangle intersection, including its boundary.
    dx,dy=b[0]-a[0],b[1]-a[1]
    lo,hi=0.,1.
    for p,q in [(-dx,a[0]-(x-hw)),(dx,x+hw-a[0]),(-dy,a[1]-(y-hh)),(dy,y+hh-a[1])]:
        if abs(p)<1e-12:
            if q<0:return False
        elif p<0:lo=max(lo,q/p)
        else:hi=min(hi,q/p)
        if lo>hi:return False
    return True


@dataclass
class Route:
    points: list
    kinds: list
    road_ids: list
    length: float
    snap_distances: list
    unconfirmed: int
    junctions: list = field(default_factory=list)

    def reversed(self):
        return Route(list(reversed(self.points)), list(reversed(self.kinds)),
                     list(reversed(self.road_ids)), self.length,
                     list(reversed(self.snap_distances)), self.unconfirmed,
                     [dict(j, at=self.length-j['at'], delta=-j['delta']) for j in reversed(self.junctions)])


class RouteError(ValueError):
    pass


def usable(road, allowed, confirmed_only):
    return road['kind'] in allowed


def build_graph(roads, anchors, allowed, confirmed_only=False, avoid=(), max_snap=45.):
    if len(anchors) < 2:
        raise RouteError('请先设置目的地并完成定位')
    if not allowed:
        raise RouteError('至少启用一种道路类型')
    if any(blocked(p,p,z) for p in anchors for z in avoid):
        raise RouteError('起点、终点或途经点在危险区域内，请调整危险区或目标点')
    segments = []
    for road in roads:
        for a, b in zip(road['points'], road['points'][1:]):
            if distance(a, b) < .05:
                continue
            segments.append((tuple(a), tuple(b), road))
    if not segments:
        raise RouteError('当前规则下没有可用道路；可检查道路分类与避让区')
    splits = [[(0., a), (1., b)] for a, b, _ in segments]
    # A spatial index keeps image-derived road networks responsive. It does not
    # connect intersections: the same explicit-vertex rule is evaluated below.
    buckets={};cell=24.
    for j,(a,b,_) in enumerate(segments):
        for gx in range(math.floor((min(a[0],b[0])-1.5)/cell),math.floor((max(a[0],b[0])+1.5)/cell)+1):
            for gy in range(math.floor((min(a[1],b[1])-1.5)/cell),math.floor((max(a[1],b[1])+1.5)/cell)+1):
                buckets.setdefault((gx,gy),[]).append(j)
    # Connect explicit vertices close to segment interiors. Geometric crossings
    # alone do NOT imply a junction (bridges and underpasses remain separate).
    for i, (a, b, _) in enumerate(segments):
        for p in (a, b):
            for j in buckets.get((math.floor(p[0]/cell),math.floor(p[1]/cell)),[]):
                if i == j:
                    continue
                c,d,_=segments[j]
                gap, q, t = project(p, c, d)
                if gap < 1.5:
                    splits[j].append((t, p))
    snapped, gaps = [], []
    for anchor in anchors:
        options = []
        for i,(a,b,road) in enumerate(segments):
            if not usable(road,allowed,confirmed_only):continue
            projection=project(anchor,a,b)
            if not any(blocked(projection[1],projection[1],z) for z in avoid):
                options.append((projection,i))
        if not options:
            raise RouteError('当前规则下没有可用道路；可检查道路分类与避让区')
        (gap, q, t), index = min(options, key=lambda x: x[0][0])
        if gap > max_snap:
            raise RouteError(f'起终点或途经点距可用道路过远（{gap:.0f} 地图像素），请补画连接路或调整位置')
        splits[index].append((t, q))
        snapped.append(q)
        gaps.append(gap)
    nodes, adjacency, node_buckets = [], {}, {}
    def node(p):
        gx,gy=math.floor(p[0]/1.5),math.floor(p[1]/1.5)
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for i in node_buckets.get((gx+dx,gy+dy),[]):
                    if distance(p,nodes[i])<1.5:return i
        nodes.append(p)
        adjacency[len(nodes)-1] = []
        node_buckets.setdefault((gx,gy),[]).append(len(nodes)-1)
        return len(nodes)-1
    factors = {'major': 1., 'minor': 1.18, 'offroad': 1.6}
    for (_, _, road), divisions in zip(segments, splits):
        division_nodes = [node(p) for _, p in sorted(divisions, key=lambda item: item[0])]
        for u, v in zip(division_nodes, division_nodes[1:]):
            if u == v:
                continue
            weight = distance(nodes[u], nodes[v])*factors[road['kind']]
            adjacency[u].append((v, weight, road))
            adjacency[v].append((u, weight, road))
    anchor_ids = [node(p) for p in snapped]
    return nodes, adjacency, anchor_ids, gaps


def plan(roads, anchors, allowed, confirmed_only=False, avoid=(), max_snap=45.):
    nodes, adjacency, anchor_ids, gaps = build_graph(roads, anchors, allowed, confirmed_only, avoid, max_snap)
    route_nodes, route_roads = [], []
    for start, end in zip(anchor_ids, anchor_ids[1:]):
        queue, costs, previous = [(0, start)], {start: 0}, {}
        while queue:
            cost, u = heapq.heappop(queue)
            if cost > costs[u]:
                continue
            if u == end:
                break
            for v, weight, road in adjacency[u]:
                if not usable(road, allowed, confirmed_only) or any(blocked(nodes[u],nodes[v],z) for z in avoid):
                    continue
                new_cost = cost + weight
                if new_cost < costs.get(v, math.inf):
                    costs[v] = new_cost
                    previous[v] = (u, road)
                    heapq.heappush(queue, (new_cost, v))
        if end not in costs:
            raise RouteError('道路不连通，当前规则和途经点之间无可行路线')
        chain, chain_roads, cur = [end], [], end
        while cur != start:
            cur, road = previous[cur]
            chain.append(cur)
            chain_roads.append(road)
        chain.reverse()
        chain_roads.reverse()
        route_nodes.extend(chain if not route_nodes else chain[1:])
        route_roads.extend(chain_roads)
    points = [nodes[i] for i in route_nodes]
    if len(points) < 2:
        raise RouteError('起点与终点太近，请选择更远的目的地')
    result = Route(points, [r['kind'] for r in route_roads], [r['id'] for r in route_roads],
                 sum(distance(a, b) for a, b in zip(points, points[1:])), gaps,
                 0)
    result.junctions = junctions_on_route(nodes, adjacency, result)
    return result


def point_at(points, lengths, s):
    from bisect import bisect_right
    s = max(0., min(lengths[-1], s))
    i = min(len(points)-2, bisect_right(lengths, s)-1)
    f = (s-lengths[i])/max(lengths[i+1]-lengths[i], 1e-9)
    return tuple(points[i][k]+f*(points[i+1][k]-points[i][k]) for k in (0,1))


def remaining_points(route, progress):
    """Clip at accepted navigation progress, including the current segment."""
    if not route or len(route.points)<2:return []
    lengths=cumulative(route.points)
    if progress>=lengths[-1]:return []
    progress=max(0.,progress)
    return [point_at(route.points,lengths,progress),
            *(p for p,s in zip(route.points,lengths) if s>progress)]


def junctions_on_route(nodes, adjacency, route):
    """Physical branches, independent of road IDs, policy, or simple road bends."""
    lengths = cumulative(route.points)
    result = []
    for u, edges in adjacency.items():
        neighbours = set(v for v, _, _ in edges)
        if len(neighbours) < 3:
            continue
        headings = []
        for v in neighbours:
            prev, cur = u, v
            travelled = distance(nodes[u], nodes[v])
            visited = {u, v}
            while travelled < 8:
                onward = set(w for w, _, _ in adjacency[cur]) - {prev}
                if len(onward) != 1:
                    break
                nxt = next(iter(onward))
                if nxt in visited:
                    break
                travelled += distance(nodes[cur],nodes[nxt])
                visited.add(nxt)
                prev, cur = cur, nxt
            heading = bearing(nodes[u], nodes[cur])
            if not any(abs(angle_delta(h,heading)) < 18 for h in headings):
                headings.append(heading)
        if len(headings) < 3:
            continue
        projection = nearest_on_route(nodes[u], route.points)
        if projection is None or projection[0] > 1.5:
            continue
        s = projection[1]
        if s < 2 or s > route.length-2:
            continue
        center = point_at(route.points,lengths,s)
        incoming = bearing(point_at(route.points,lengths,s-8),center)
        outgoing = bearing(center,point_at(route.points,lengths,s+8))
        result.append({'at':s,'delta':angle_delta(incoming,outgoing)})
    result.sort(key=lambda j:j['at'])
    # Nearby vertices can represent the same wide junction.
    merged = []
    for item in result:
        if merged and item['at']-merged[-1]['at'] < 3:
            if abs(item['delta']) > abs(merged[-1]['delta']):merged[-1]=item
        else:merged.append(item)
    return merged


def cumulative(points):
    result = [0.]
    for a, b in zip(points, points[1:]):
        result.append(result[-1]+distance(a, b))
    return result


def nearest_on_route(point, points, minimum_progress=0., maximum_progress=math.inf):
    distances = cumulative(points)
    options = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        gap, q, t = project(point, a, b)
        s = distances[i] + t*distance(a, b)
        if minimum_progress <= s <= maximum_progress:
            options.append((gap, s, i, q))
    return min(options, default=None, key=lambda item: item[0])
