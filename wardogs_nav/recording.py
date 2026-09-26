"""Build roads from accepted visual positions; never connect across lost fixes."""
from copy import deepcopy
import math
from .model import uid
from .routing import distance,project,cumulative,nearest_on_route,bridge_ports


def simplify(points,tolerance):
    if len(points)<3:return [list(p) for p in points]
    keep={0,len(points)-1};stack=[(0,len(points)-1)]
    while stack:
        a,b=stack.pop()
        if b-a<2:continue
        gap,index=max((project(points[i],points[a],points[b])[0],i) for i in range(a+1,b))
        if gap>tolerance:keep.add(index);stack.extend(((a,index),(index,b)))
    return [list(points[i]) for i in sorted(keep)]


class SegmentIndex:
    def __init__(self,roads=(),cell=24.):
        self.cell=cell;self.cells={}
        for road in roads:self.add(road)

    def keys(self,a,b,pad=2.):
        for x in range(math.floor((min(a[0],b[0])-pad)/self.cell),math.floor((max(a[0],b[0])+pad)/self.cell)+1):
            for y in range(math.floor((min(a[1],b[1])-pad)/self.cell),math.floor((max(a[1],b[1])+pad)/self.cell)+1):yield x,y

    def add(self,road):
        for a,b in zip(road['points'],road['points'][1:]):
            if distance(a,b)<.01:continue
            item=(a,b,road)
            for key in self.keys(a,b):self.cells.setdefault(key,[]).append(item)

    def near(self,a,b,pad=2.):
        found={}
        for key in self.keys(a,b,pad):
            for item in self.cells.get(key,[]):found[id(item)]=item
        return found.values()

    def covering(self,a,b,tolerance=1.5):
        mid=[(a[k]+b[k])/2 for k in (0,1)];options=[]
        for c,d,road in self.near(a,b,tolerance):
            length=distance(a,b)*distance(c,d)
            if length<1e-8:continue
            aligned=abs(sum((b[k]-a[k])*(d[k]-c[k]) for k in (0,1)))/length
            gap,q,_=project(mid,c,d)
            if aligned>.8 and gap<=tolerance:options.append((gap,q,c,d,road))
        return min(options,key=lambda x:x[0]) if options else None


def intersection(a,b,c,d):
    u=[b[k]-a[k] for k in (0,1)];v=[d[k]-c[k] for k in (0,1)]
    cross=lambda x,y:x[0]*y[1]-x[1]*y[0]
    det=cross(u,v)
    if abs(det)<1e-9:return None
    w=[c[k]-a[k] for k in (0,1)];t=cross(w,v)/det;s=cross(w,u)/det
    if -1e-8<=t<=1+1e-8 and -1e-8<=s<=1+1e-8:
        return max(0.,min(1.,t)),[a[k]+t*u[k] for k in (0,1)]


def add_recorded_roads(roads,traces,scale=1.,source='manual'):
    """Skip covered spans, split actual ground intersections, retain bridge levels."""
    result=deepcopy(roads);index=SegmentIndex(result);added=[]
    minimum=max(1.5,8/scale)
    for trace in traces:
        run=[];previous=None
        def flush():
            nonlocal run
            if len(run)>1 and cumulative(run)[-1]>=minimum:
                points=simplify(run,max(.3,2/scale))
                for offset in range(0,len(points)-1,1999):
                    road=dict(id=uid(),name=('自动记录' if source=='auto' else '行驶记录')+' · 越野',
                              kind='offroad',confirmed=True,points=points[offset:offset+2000],recording=source)
                    result.append(road);index.add(road);added.append(road['id'])
            run=[]
        for a,b in zip(trace,trace[1:]):
            length=distance(a,b)
            if length<.01:continue
            divisions={0.:list(a),1.:list(b)};cuts=[]
            n=max(1,math.ceil(length/1.))
            for i in range(1,n):divisions[i/n]=[a[k]+(b[k]-a[k])*i/n for k in (0,1)]
            for c,d,road in list(index.near(a,b)):
                hit=intersection(a,b,c,d)
                if hit and (not road.get('bridge') or any(distance(hit[1],p)<1.5 for p in bridge_ports(road))):
                    divisions[hit[0]]=hit[1];cuts.append(hit[1])
            ordered=[p for _,p in sorted(divisions.items())]
            for p,q in zip(ordered,ordered[1:]):
                if distance(p,q)<1e-8:continue
                covered=index.covering(p,q)
                if covered:
                    if run:run.append(list(project(p,covered[2],covered[3])[1]));flush()
                    previous=covered
                    continue
                if not run:
                    run=[list(project(p,previous[2],previous[3])[1]) if previous else list(p)]
                if distance(run[-1],q)>.01:run.append(list(q))
                previous=None
                if any(distance(q,cut)<1e-6 for cut in cuts):flush()
        flush()
    # Live automatic promotion extends untouched recorder roads at degree-two
    # joins, rather than leaving one separately editable road per sample block.
    if source=='auto' and added:
        merging=True
        while merging:
            merging=False
            for road in list(result):
                if road['id'] not in added:continue
                for other in result:
                    if other is road or other.get('recording')!='auto' or other.get('kind')!='offroad' or other.get('bridge'):continue
                    for i in (0,-1):
                        for j in (0,-1):
                            join=road['points'][i]
                            if distance(join,other['points'][j])>=1.5:continue
                            if any(r is not road and r is not other and not r.get('bridge') and
                                   any(project(join,a,b)[0]<1.5 for a,b in zip(r['points'],r['points'][1:])) for r in result):continue
                            left=other['points'] if j==-1 else list(reversed(other['points']))
                            right=road['points'] if i==0 else list(reversed(road['points']))
                            points=simplify(left+right[1:],max(.3,2/scale))
                            if len(points)>2000:continue
                            other['points']=points;result.remove(road);added.remove(road['id'])
                            if other['id'] not in added:added.append(other['id'])
                            merging=True;break
                        if merging:break
                    if merging:break
                if merging:break
    return result,len(added)


class RoadRecorder:
    def __init__(self,state=None,scale=1.):
        self.scale=scale or 1.;self.state=deepcopy(state or {})
        self.state.setdefault('manual',[]);self.state.setdefault('active',False);self.state.setdefault('units',[])
        self.last=None;self.last_time=None;self.current=None;self.seed=[];self.tail=None
        self.votes={};self.unit_index=SegmentIndex(self.state['units']);self.roads=[];self.road_index=SegmentIndex()
        self.error='';self.dirty=False

    @property
    def active(self):return self.state['active']

    def set_roads(self,roads):
        self.roads=roads;self.road_index=SegmentIndex(roads)

    def start(self):
        self.state['manual']=[];self.state['active']=True;self.current=None;self.dirty=True

    def stop(self):
        traces=deepcopy(self.state['manual']);self.state['manual']=[];self.state['active']=False;self.current=None;self.dirty=True
        return traces

    def _seed_done(self):
        if len(self.seed)>1 and cumulative(self.seed)[-1]>=max(3.,12/self.scale):
            if len(self.state['units'])>=20000:
                self.error='自动记录候选已满，请清空累计后继续'
            else:
                unit=dict(id=uid(),points=simplify(self.seed,.25),count=1,added=False)
                self.state['units'].append(unit);self.unit_index.add(unit)
                length=cumulative(unit['points'])[-1]
                self.votes[unit['id']]=(1,length,length)
                self.dirty=True
        self.seed=[]

    def disconnect(self):
        self._seed_done();self.last=None;self.last_time=None;self.current=None;self.tail=None;self.votes.clear()

    def clear_counts(self):
        self.state['units']=[];self.unit_index=SegmentIndex();self.seed=[];self.tail=None;self.votes.clear();self.dirty=True

    def feed(self,point,now,automatic=False):
        p=list(point)
        if not self.active and not automatic:return
        if self.last_time is not None and (now-self.last_time>2.5 or now<=self.last_time or
            distance(p,self.last)*self.scale>max(60.,80*(now-self.last_time))):self.disconnect()
        if self.last is None:
            self.last=p;self.last_time=now
            if self.active:self.current=[p];self.state['manual'].append(self.current);self.dirty=True
            return
        self.last_time=now
        if distance(p,self.last)<max(.8,3/self.scale):return
        if self.active:
            if self.current is None:self.current=[self.last];self.state['manual'].append(self.current)
            if len(self.current)>1:
                a,b=self.current[-2:];u=[b[k]-a[k] for k in (0,1)];v=[p[k]-b[k] for k in (0,1)]
                if sum(u[k]*v[k] for k in (0,1))<-.5*distance(a,b)*distance(b,p):
                    self.current=[b];self.state['manual'].append(self.current)
            self.current.append(p);self.dirty=True
        if automatic:
            n=max(1,math.ceil(distance(self.last,p)/.75))
            for i in range(n):
                a=[self.last[k]+(p[k]-self.last[k])*i/n for k in (0,1)]
                b=[self.last[k]+(p[k]-self.last[k])*(i+1)/n for k in (0,1)]
                self._observe(a,b)
        self.last=p

    def _observe(self,a,b):
        tolerance=1.5
        nearby={u['id']:u for _,_,u in self.unit_index.near(a,b)}
        covered=None
        for unit in nearby.values():
            pa=nearest_on_route(a,unit['points']);pb=nearest_on_route(b,unit['points']);length=cumulative(unit['points'])[-1]
            if max(pa[0],pb[0])>tolerance:continue
            movement=pb[1]-pa[1]
            if abs(movement)<distance(a,b)*.6:continue
            direction=1 if movement>0 else -1
            old=self.votes.get(unit['id'])
            start=old[1] if old and old[0]==direction and abs(old[2]-pa[1])<tolerance else pa[1]
            if abs(pb[1]-start)>=length*.8:
                unit['count']=min(100,unit['count']+1);start=pb[1];self.dirty=True
            self.votes[unit['id']]=(direction,start,pb[1])
            covered=pb[3]
        road=self.road_index.covering(a,b)
        if covered is not None or road:
            self._seed_done();self.tail=list(covered if covered is not None else project(b,road[2],road[3])[1]);return
        if not self.seed:self.seed=[self.tail or list(a)]
        self.seed.append(list(b));self.tail=list(b)
        if cumulative(self.seed)[-1]>=max(6.,24/self.scale):
            self._seed_done();self.seed=[list(b)]

    def ready(self,minimum):
        return [u for u in self.state['units'] if not u['added'] and u['count']>=minimum]

    def promoted(self,units):
        for unit in units:unit['added']=True
        self.dirty=True
