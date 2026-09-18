"""Filter and trace candidate pavement on the additional public map images."""
from pathlib import Path
import argparse,json,sys
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wardogs_nav.vision import read_image
from wardogs_nav.model import atomic_json,validate_project
from tools.extract_roads import thin,trace_gap
from wardogs_nav.routing import project as project_point


# These short corridors were inspected on the public colour image. In
# particular, nearby river banks are not joined merely because they are close.
CONNECTIONS={
    'bakurani':[
        ('西部村镇西入口','major',[[229,1018],[265.5,1017.5]]),
        ('西部村镇东入口','major',[[367,972.5],[390,973]]),
        ('北部干道断点','major',[[1406.5,221],[1408.5,253.5]]),
        ('北部厂区接入','minor',[[1390.5,337],[1393,335]]),
        ('北部谷地接入','minor',[[1201,550],[1206,550]]),
        ('中北部路口接入','minor',[[1091.5,841.5],[1095.5,843]]),
        ('中部村镇北入口','minor',[[1072.5,897.5],[1079.5,912]]),
        ('中部村镇东入口','minor',[[1119.5,1029.5],[1123.5,1027]]),
        ('东北农田道路接入','major',[[1277,1027],[1286.5,1028.5]]),
        ('东南干道断点','major',[[1388,1519.5],[1391,1514]]),
        ('西北山路接入','minor',[[905.5,821],[926.5,835.5]]),
        ('南部营地道路','minor',[[1115,1730],[1125,1751],[1144,1774],[1164,1792],[1188,1804]]),
    ],
    'zestafona':[
        ('北部桥头接入','major',[[726.5,312.5],[729.5,312]]),
        ('西部桥头接入','minor',[[802.5,646.5],[803.5,659.5]]),
        ('西部村镇道路接入','minor',[[853,639.5],[865.5,647.5]]),
        ('北侧跨河道路接入','major',[[854,467.5],[854.5,451.5]]),
        ('城市北入口','minor',[[962.5,565],[968.5,572.5]]),
        ('东北桥头接入','major',[[1034,535],[1041,544]]),
        ('东南干道断点','major',[[1144.5,968],[1150,972]]),
        ('城市东入口','minor',[[1034,772],[1037,775.5]]),
    ],
}


def connect_inspected(roads,mask,map_id):
    def snap(p):
        gap,q,_=min((project_point(p,a,b) for r in roads for a,b in zip(r['points'],r['points'][1:])),key=lambda v:v[0])
        return list(q) if gap<10 else list(p)
    for name,kind,guide in CONNECTIONS[map_id]:
        points=[list(p) for p in guide];points[0]=snap(points[0]);points[-1]=snap(points[-1])
        traced=trace_gap(mask,points);traced[0]=points[0];traced[-1]=points[-1]
        roads.append(dict(id=f'{map_id}-link-{len(roads)+1:03}',name=name,kind=kind,confirmed=False,
                          note='按公开底图核对接入口，沿图上道路补齐；实际通行性待实测',points=traced))


def extract(map_id):
    cv2.setNumThreads(2)
    folder=ROOT/'research/maps'/map_id;assets=ROOT/'assets/maps'/map_id
    project=json.loads((assets/'project.json').read_text(encoding='utf-8'))
    image=read_image(assets/'map.png');h,w=image.shape[:2];mpp=project['meters_per_pixel']
    color=cv2.resize(read_image(folder/'clean-color-z5.png'),(w*2,h*2),interpolation=cv2.INTER_AREA)
    gray=cv2.resize(read_image(folder/'clean-grayscale-z5.png'),(w*2,h*2),interpolation=cv2.INTER_AREA)[:,:,0]
    hsv=cv2.cvtColor(color,cv2.COLOR_BGR2HSV)
    # Roads are pale and low-saturation. Dark river beds, bright snow, and
    # saturated vegetation are deliberately excluded rather than connected.
    mask=((hsv[:,:,1]<100)&(hsv[:,:,2]>105)&(gray>45)&(gray<115)).astype(np.uint8)*255
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    _,holes,hs,_=cv2.connectedComponentsWithStats(255-mask,8)
    mask[np.isin(holes,np.where(hs[:,cv2.CC_STAT_AREA]<70)[0])]=255
    _,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    mask[np.isin(labels,np.where(stats[:,cv2.CC_STAT_AREA]<80)[0])]=0
    del holes,labels,hsv,color
    width=cv2.distanceTransform(mask,cv2.DIST_L2,5)
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
            if second in critical or (start,second) in visited:continue
            chain=[start,second];previous,current=start,second
            while current not in critical:
                choices=[p for p in adjacent[current] if p!=previous]
                if not choices:break
                previous,current=current,choices[0];chain.append(current)
            for a,b in zip(chain,chain[1:]):visited.add((a,b));visited.add((b,a))
            if current not in labels:continue
            points=np.array(chain,dtype=float);points[0]=centers[labels[start]];points[-1]=centers[labels[current]]
            length=float(np.linalg.norm(np.diff(points,axis=0),axis=1).sum())
            width_m=float(np.median([width[y,x] for y,x in chain]))*mpp
            if width_m>24:continue
            edges.append(dict(a=labels[start],b=labels[current],pixels=chain,points=points,length=length))
    for _ in range(8):
        degree={}
        for e in edges:
            for k in ('a','b'):degree[e[k]]=degree.get(e[k],0)+1
        clean=[e for e in edges if not(e['length']<45 and (degree[e['a']]==1 or degree[e['b']]==1)) and not(e['a']==e['b'] and e['length']<80)]
        if len(clean)==len(edges):break
        edges=clean
    connection={}
    for i,e in enumerate(edges):
        for k in ('a','b'):connection.setdefault(e[k],[]).append(i)
    keep=set();seen=set();components=[]
    for i in range(len(edges)):
        if i in seen:continue
        stack=[i];group=set()
        while stack:
            j=stack.pop()
            if j in group:continue
            group.add(j);seen.add(j)
            for k in ('a','b'):stack.extend(n for n in connection[edges[j][k]] if n not in group)
        length=sum(edges[j]['length'] for j in group)*mpp/2
        # Isolated roofs and rock fragments do not form sustained road networks.
        if length>=650:keep.update(group);components.append({'edges':len(group),'length_m':round(length)})
    edges=[edges[i] for i in sorted(keep)]
    while True:
        incident={}
        for i,e in enumerate(edges):
            for k in ('a','b'):incident.setdefault(e[k],[]).append(i)
        junction=next((k for k,ids in incident.items() if len(ids)==2 and len(set(ids))==2),None)
        if junction is None:break
        i,j=incident[junction];a,b=edges[i],edges[j]
        if a['a']==junction:a=dict(a,a=a['b'],b=a['a'],points=a['points'][::-1],pixels=a['pixels'][::-1])
        if b['b']==junction:b=dict(b,a=b['b'],b=b['a'],points=b['points'][::-1],pixels=b['pixels'][::-1])
        merged=dict(a=a['a'],b=b['b'],pixels=a['pixels']+b['pixels'][1:],points=np.concatenate([a['points'],b['points'][1:]]),length=a['length']+b['length'])
        edges=[e for k,e in enumerate(edges) if k not in (i,j)]+[merged]
    roads=[]
    for e in edges:
        points=e['points'][:,::-1]/2
        simple=cv2.approxPolyDP(np.float32(points),.6,False)[:,0].round(2).tolist()
        if len(simple)<2:continue
        road_width=float(np.median([width[y,x] for y,x in e['pixels']]))*mpp
        kind='major' if road_width>=12 else 'minor'
        roads.append(dict(id=f'{map_id}-road-{len(roads)+1:03}',name=f'图像道路 {len(roads)+1:03}',kind=kind,
                          confirmed=False,note=f'公开底图滤镜候选，估计路宽 {road_width:.1f} 米；路级、坡度和通行性待实测',points=simple))
    connect_inspected(roads,mask,map_id)
    for road in roads:
        cv2.polylines(image,[np.int32(road['points'])],False,(40,205,250) if road['kind']=='major' else (225,173,95),1,cv2.LINE_AA)
    project['roads']=roads
    atomic_json(assets/'project.json',validate_project(project))
    cv2.imencode('.png',image)[1].tofile(str(folder/'road-candidates.png'))
    cv2.imencode('.png',cv2.resize(mask,(w,h),interpolation=cv2.INTER_NEAREST))[1].tofile(str(folder/'pavement-mask.png'))
    atomic_json(folder/'road-extraction.json',dict(roads=len(roads),major=sum(r['kind']=='major' for r in roads),components=sorted(components,key=lambda c:-c['length_m'])))
    print(map_id,'roads',len(roads),'components',len(components),'largest',sorted(components,key=lambda c:-c['length_m'])[:5],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--map',choices=['bakurani','zestafona'],required=True)
    extract(p.parse_args().map)
