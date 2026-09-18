"""Build reviewable road candidates from the public, overlay-free terrain tiles.

Colour separates pavement from vegetation; explicit water exclusions prevent the
similarly coloured river bed becoming a road. All output remains unconfirmed.
"""
from pathlib import Path
import json,sys,math,heapq
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wardogs_nav.vision import read_image
from wardogs_nav.routing import project


def thin(binary):
    a=(binary>0).astype(np.uint8)
    for _ in range(100):
        changed=False
        for phase in (0,1):
            p=np.pad(a,1);n=[p[:-2,1:-1],p[:-2,2:],p[1:-1,2:],p[2:,2:],p[2:,1:-1],p[2:,:-2],p[1:-1,:-2],p[:-2,:-2]]
            count=sum(n);trans=sum(((n[i]==0)&(n[(i+1)%8]>0)).astype(np.uint8) for i in range(8))
            if phase==0:keep=(n[0]*n[2]*n[4]==0)&(n[2]*n[4]*n[6]==0)
            else:keep=(n[0]*n[2]*n[6]==0)&(n[0]*n[4]*n[6]==0)
            remove=(a>0)&(count>=2)&(count<=6)&(trans==1)&keep
            if remove.any():a[remove]=0;changed=True
        if not changed:break
    return a


def trace_gap(mask,waypoints):
    """Follow pavement inside an inspected corridor; never invent a straight link."""
    guide=np.zeros_like(mask);cv2.polylines(guide,[np.int32(waypoints)*2],False,255,32)
    yy,xx=np.where(guide);x0,x1=xx.min(),xx.max()+1;y0,y1=yy.min(),yy.max()+1
    surface=mask[y0:y1,x0:x1]>0;allowed=guide[y0:y1,x0:x1]>0
    distance=cv2.distanceTransform(surface.astype(np.uint8),cv2.DIST_L2,5)
    def cell(p):return (round(p[1]*2)-y0,round(p[0]*2)-x0)
    start,finish=cell(waypoints[0]),cell(waypoints[-1]);costs={start:0.};parents={};queue=[(0.,start)]
    while queue:
        _,u=heapq.heappop(queue)
        if u==finish:break
        for dy,dx in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
            v=(u[0]+dy,u[1]+dx)
            if not(0<=v[0]<surface.shape[0] and 0<=v[1]<surface.shape[1] and allowed[v]):continue
            step=math.hypot(dy,dx)*(1+2/(1+distance[v]) if surface[v] else 24)
            cost=costs[u]+step
            if cost<costs.get(v,math.inf):
                costs[v]=cost;parents[v]=u;heapq.heappush(queue,(cost+math.dist(v,finish),v))
    if finish not in costs:raise RuntimeError('Road repair corridor has no path')
    chain=[finish]
    while chain[-1]!=start:chain.append(parents[chain[-1]])
    points=np.array([[p[1]+x0,p[0]+y0] for p in chain[::-1]],np.float32)/2
    return cv2.approxPolyDP(points,.5,False)[:,0].round(2).tolist()


def main():
    cv2.setNumThreads(2)
    meta=json.loads((ROOT/'research/clean-registration.json').read_text());matrix=np.diag([2.,2.,1.])@np.array(meta['reference_to_map'])
    color=cv2.warpPerspective(read_image(ROOT/'research/clean-color-z5.png'),matrix,(3190,2902))
    gray=cv2.warpPerspective(read_image(ROOT/'research/clean-grayscale-z5.png'),matrix,(3190,2902))[:,:,0]
    hsv=cv2.cvtColor(color,cv2.COLOR_BGR2HSV)
    mask=((hsv[:,:,1]<100)&(gray>45)&(gray<110)).astype(np.uint8)*255
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    # Texture speckles inside continuous pavement must not become tiny loops.
    _,holes,hs,_=cv2.connectedComponentsWithStats(255-mask,8)
    mask[np.isin(holes,np.where(hs[:,cv2.CC_STAT_AREA]<90)[0])]=255
    pavement=mask.copy()
    water=np.zeros_like(mask)
    rivers=[(30,[(585,0),(565,65),(522,120),(500,180),(459,225),(410,267),(381,310),(353,363),(343,427),(357,461),(331,492),(311,531),(280,596),(244,643),(210,675),(170,698)]),
      (32,[(0,907),(42,855),(60,795),(65,752),(100,714),(155,708),(207,692),(265,702),(306,700),(348,685)]),
      (27,[(348,685),(381,712),(430,726),(480,728),(530,716),(572,735),(612,751),(655,753),(690,732),(730,734),(765,743),(811,742),(856,748),(900,771),(930,799),(977,771),(1018,744),(1050,743),(1098,780),(1120,819),(1170,838),(1227,851),(1300,844),(1360,842),(1398,824),(1430,786),(1476,724),(1504,682),(1568,652),(1594,653)])]
    for width,points in rivers:cv2.polylines(water,[np.int32(points)*2],False,255,width*2)
    # Only restore the pavement already visible at inspected bridge crossings.
    bridges=[[(312,326),(390,341)],[(409,761),(451,694)],[(651,706),(699,779)],[(765,705),(765,784)],[(1182,801),(1208,895)],[(1366,794),(1445,861)]]
    for points in bridges:cv2.polylines(water,[np.int32(points)*2],False,0,14)
    mask[water>0]=0
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    mask[np.isin(labels,np.where(stats[:,cv2.CC_STAT_AREA]<80)[0])]=0
    dist=cv2.distanceTransform(mask,cv2.DIST_L2,5)
    skeleton=thin(mask)
    pixels=set(zip(*np.where(skeleton)))
    def neighbors(p):
        y,x=p;result=[]
        for dy,dx in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
            q=(y+dy,x+dx)
            if q not in pixels:continue
            if dy and dx and ((y+dy,x) in pixels or (y,x+dx) in pixels):continue
            result.append(q)
        return result
    adjacent={p:neighbors(p) for p in pixels}
    critical={p for p,ns in adjacent.items() if len(ns)!=2}
    labels={};centers={}
    for p in sorted(critical):
        if p in labels:continue
        index=len(centers);stack=[p];group=[];labels[p]=index
        while stack:
            u=stack.pop();group.append(u)
            for v in adjacent[u]:
                if v in critical and v not in labels:labels[v]=index;stack.append(v)
        centers[index]=np.mean(group,axis=0)
    visited=set();edges=[]
    for start in sorted(critical):
        for second in adjacent[start]:
            if second in critical:continue
            if (start,second) in visited:continue
            chain=[start,second];previous,current=start,second
            while current not in critical:
                choices=[p for p in adjacent[current] if p!=previous]
                if not choices:break
                previous,current=current,choices[0];chain.append(current)
            for a,b in zip(chain,chain[1:]):visited.add((a,b));visited.add((b,a))
            if current not in labels:continue
            points=np.array(chain,dtype=float);points[0]=centers[labels[start]];points[-1]=centers[labels[current]]
            length=float(np.linalg.norm(np.diff(points,axis=0),axis=1).sum())
            width_m=float(np.median([dist[y,x] for y,x in chain]))*5.357
            # Broad river-bank remnants and building/parking pads are not road
            # centerlines even when they share the pavement colour.
            if width_m>23:continue
            edges.append({'a':labels[start],'b':labels[current],'pixels':chain,'points':points,'length':length})
    # Remove short branches generated by roofs and small pavement patches.
    for _ in range(8):
        degree={}
        for e in edges:
            for k in ('a','b'):degree[e[k]]=degree.get(e[k],0)+1
        clean=[e for e in edges if not (e['length']<45 and (degree[e['a']]==1 or degree[e['b']]==1)) and not(e['a']==e['b'] and e['length']<80)]
        if len(clean)==len(edges):break
        edges=clean
    # Keep connected networks of at least 250 map pixels, eliminating isolated roofs.
    connection={}
    for i,e in enumerate(edges):
        for k in ('a','b'):connection.setdefault(e[k],[]).append(i)
    keep=set();seen=set()
    for i in range(len(edges)):
        if i in seen:continue
        stack=[i];group=set()
        while stack:
            j=stack.pop()
            if j in group:continue
            group.add(j);seen.add(j)
            for k in ('a','b'):stack.extend(n for n in connection[edges[j][k]] if n not in group)
        # Keep terrain components connected to inspected public-road anchors.
        anchors=np.array([[480,1160],[1315,796],[670,590],[208,226],[60,960]])*2
        near_anchor=any(np.min(np.linalg.norm(e['points'][:,::-1,None]-anchors.T,axis=1))<30 for e in (edges[j] for j in group))
        if near_anchor:keep.update(group)
    edges=[edges[i] for i in sorted(keep)]
    # Pruning leaves degree-two junctions; merge them into usable editable roads.
    while True:
        incident={}
        for i,e in enumerate(edges):
            for k in ('a','b'):incident.setdefault(e[k],[]).append(i)
        junction=next((k for k,ids in incident.items() if len(ids)==2 and len(set(ids))==2),None)
        if junction is None:break
        i,j=incident[junction];a,b=edges[i],edges[j]
        if a['a']==junction:a=dict(a,a=a['b'],b=a['a'],points=a['points'][::-1],pixels=a['pixels'][::-1])
        if b['b']==junction:b=dict(b,a=b['b'],b=b['a'],points=b['points'][::-1],pixels=b['pixels'][::-1])
        merged={'a':a['a'],'b':b['b'],'pixels':a['pixels']+b['pixels'][1:],'points':np.concatenate([a['points'],b['points'][1:]]),'length':a['length']+b['length']}
        edges=[e for k,e in enumerate(edges) if k not in (i,j)]+[merged]
    roads=[]
    preview=read_image(ROOT/'research/clean-aligned.png')
    for e in edges:
        points=e['points'][:,::-1]/2
        simple=cv2.approxPolyDP(np.float32(points),.6,False)[:,0].round(2).tolist()
        width_m=float(np.median([dist[y,x] for y,x in e['pixels']]))*5.357
        kind='major' if width_m>=12 else 'minor'
        roads.append({'id':f'clean-{len(roads)+1:03}','name':f'图像道路 {len(roads)+1:03}','kind':kind,'confirmed':False,'note':f'干净底图滤镜提取；估计图上路宽 {width_m:.1f} 米，路级与通行性待实测','points':simple})
        cv2.polylines(preview,[np.int32(simple)],False,(40,205,250) if kind=='major' else (225,173,95),1,cv2.LINE_AA)
    repairs=[('西北桥接入','minor',[[375,350],[376,365],[372,385]]),
      ('西部干道接入','major',[[173,630],[213,640],[268,655]]),
      ('西南跨河桥','minor',[[439,710],[428,730],[408,758]]),
      ('中部斜桥','major',[[664,711],[680,737],[696,765]]),
      ('中部直桥','minor',[[765,710],[764,734],[765,767]]),
      ('东部跨河桥','major',[[1380,807],[1400,827],[1425,846]]),
      ('南基地出口','minor',[[481,1208],[482,1230],[481,1255]]),
      ('南基地东北出口','minor',[[481,1255],[494,1250],[505,1241],[525,1223],[534,1208],[534,1184],[530,1160],[537,1137],[545,1114]]),
      ('西南地图边界接入','minor',[[84,734],[73,765],[75,803]])]
    def snap(p):
        gap,q,_=min((project(p,a,b) for r in roads for a,b in zip(r['points'],r['points'][1:])),key=lambda v:v[0])
        return list(q) if gap<16 else p
    for name,kind,points in repairs:
        points[0]=snap(points[0]);points[-1]=snap(points[-1])
        traced=trace_gap(pavement,points)
        traced[0]=points[0];traced[-1]=points[-1]
        roads.append({'id':f'clean-{len(roads)+1:03}','name':name,'kind':kind,'confirmed':False,'note':'已核对图上接入口与桥位，中心线沿铺装滤镜寻路；实际通行性待实测','points':traced})
        cv2.polylines(preview,[np.int32(traced)],False,(100,250,100),1,cv2.LINE_AA)
    for name,points in [('东南开阔地候选',[[1200,949],[1169,931],[1136,910],[1107,889],[1080,867]]),('南部农田候选',[[562,1000],[587,1020],[611,1040],[637,1052]])]:
        points[0]=snap(points[0]);points[-1]=snap(points[-1])
        roads.append({'id':f'clean-{len(roads)+1:03}','name':name,'kind':'offroad','confirmed':False,'note':'图上树木较少的候选方向；坡度、地表与通行性未实测，默认禁用；不能判断地雷','points':points})
    report={'roads':roads,'water_exclusions':rivers,'bridges':bridges}
    (ROOT/'research/extracted-roads.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    cv2.imwrite(str(ROOT/'research/road-candidates.png'),preview)
    cv2.imwrite(str(ROOT/'research/pavement-mask.png'),mask)
    print('roads',len(roads),'major',sum(r['kind']=='major' for r in roads),'points',sum(len(r['points']) for r in roads),flush=True)


if __name__=='__main__':main()
