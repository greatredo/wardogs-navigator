from dataclasses import dataclass, field
import math
from .routing import cumulative, distance, bearing, angle_delta, nearest_on_route, point_at
from .model import NOTE_TYPES, MODIFIERS


@dataclass
class Cue:
    id: str
    at: float
    kind: str
    grade: int = 0
    text: str = ''
    lead_m: float = 0
    inferred: bool = False
    modifiers: list = field(default_factory=list)


def geometric_cues(route, scale):
    """Group sustained curvature; polyline sampling density must not set the grade."""
    # Image-derived centre lines contain pixel-sized alternating kinks. Remove
    # those before computing curvature, while keeping real sharp corners.
    from .routing import project
    points=route.points
    keep={0,len(points)-1};stack=[(0,len(points)-1)];tolerance=max(1.,8/scale)
    while stack:
        left,right=stack.pop()
        if right-left<2:continue
        gap,index=max((project(points[i],points[left],points[right])[0],i) for i in range(left+1,right))
        if gap>tolerance:keep.add(index);stack.extend([(left,index),(index,right)])
    points=[points[i] for i in sorted(keep)]
    lengths = cumulative(points)
    step = max(.75, 5/scale)
    window = max(2., 18/scale)
    samples = [i*step for i in range(1, int(lengths[-1]/step))]
    groups, group = [], []
    previous_heading = None
    for s in samples:
        heading = bearing(point_at(points,lengths,s-window),point_at(points,lengths,s+window))
        delta = 0 if previous_heading is None else angle_delta(previous_heading,heading)
        previous_heading = heading
        if abs(delta) < .35:
            if group and s-group[-1][0] > 3*step:
                groups.append(group);group=[]
            continue
        if group and (delta*group[-1][1]<0 or s-group[-1][0]>4*step):
            groups.append(group);group=[]
        group.append((s,delta))
    if group:groups.append(group)
    cues=[]
    for i,g in enumerate(groups):
        total=sum(d for _,d in g);magnitude=abs(total)
        if magnitude<12:continue
        span=(g[-1][0]-g[0][0]+step)*scale
        radius=span/max(math.radians(magnitude),.01)
        direction='right' if total>0 else 'left'
        kind=direction
        if magnitude>=150 and radius<50:kind='hairpin_'+direction
        elif 75<=magnitude<=105 and span<=max(50,scale*7):kind='square_'+direction
        grade=6 if radius>=250 else 5 if radius>=130 else 4 if radius>=70 else 3 if radius>=40 else 2 if radius>=20 else 1
        at=max(0.,g[0][0]-step/2)
        at=nearest_on_route(point_at(points,lengths,at),route.points)[1]
        cues.append(Cue(f'curve-{i}',at,kind,grade,inferred=True,
                        modifiers=['long'] if span>130 else []))
    return cues


def cues_for(route, notes, mode, scale=1.):
    points = route.points
    lengths = cumulative(points)
    cues = []
    if mode == 'normal':
        for i,junction in enumerate(route.junctions):
            delta=junction['delta'];magnitude=abs(delta)
            direction='right' if delta>0 else 'left'
            kind='straight' if magnitude<22 else 'keep_'+direction if magnitude<40 else direction if magnitude<150 else 'uturn'
            cues.append(Cue(f'junction-{i}',junction['at'],kind))
    if mode == 'wrc':
        cues = geometric_cues(route, scale or 1.)
        for note in notes:
            projection = nearest_on_route(note['point'], points)
            if projection is None or projection[0] > 25:
                continue
            _, s, i, _ = projection
            tangent=bearing(point_at(points,lengths,s-8),point_at(points,lengths,s+8))
            backwards = abs(angle_delta(note.get('bearing', 0), tangent)) > 90
            if (note['direction'] == 'forward' and backwards) or (note['direction'] == 'reverse' and not backwards):
                continue
            kind = note['type']
            modifiers=list(note.get('modifiers',[]))
            if backwards:
                kind = kind.replace('left','RIGHT').replace('right','left').replace('RIGHT','right')
                modifiers=[{'tightens':'opens','opens':'tightens'}.get(m,m) for m in modifiers]
            text = note.get('reverse_text', '') if backwards else note.get('text', '')
            directional='left' in kind or 'right' in kind
            if not text and not directional:
                text = note.get('text', '')
            if directional:
                nearby=[c for c in cues if c.inferred and abs(c.at-s)<=25]
                if nearby:cues.remove(min(nearby,key=lambda c:abs(c.at-s)))
            cues.append(Cue(note['id'], s, kind, note['grade'], text, note.get('lead_m',0),False,modifiers))
    cues.append(Cue('arrival', lengths[-1], 'arrival'))
    return sorted(cues, key=lambda c:c.at)


def cue_text(cue, mode, spoken=False):
    if cue.text:
        return cue.text
    if cue.kind == 'arrival':
        return '到达目的地'
    if cue.kind in ('left', 'right'):
        if mode == 'wrc':
            grade='一二三四五六'[max(1,min(6,cue.grade))-1] if spoken else str(cue.grade)
            text=('左' if cue.kind == 'left' else '右')+grade
        else:text='路口左转' if cue.kind == 'left' else '路口右转'
    else:
        text={'straight':'路口直行' if mode=='normal' else '直线',
              'keep_left':'路口向左前方','keep_right':'路口向右前方','uturn':'掉头'}.get(cue.kind,NOTE_TYPES.get(cue.kind,'继续前进'))
    if mode=='wrc' and cue.modifiers:text+='，'+'，'.join(MODIFIERS[m] for m in cue.modifiers)
    return text


def distance_text(value, calibrated=True):
    value=max(0,round(value/10)*10)
    if calibrated and value>=1000:return f'{value/1000:g}公里'
    return f'{value:.0f}'+('米' if calibrated else '地图单位')


class Navigator:
    def __init__(self):
        self.route = None
        self.active = False
        self.progress = 0.
        self.last_point = None
        self.last_time = None
        self.speed = 0.
        self.spoken = set()
        self.lap = 0
        self.leg = '去程'
        self.cues = []
        self.offroute_count = 0
        self.arrival_count = 0

    def start(self, route, notes, settings, scale, roundtrip=False):
        self.route = route
        self.notes = notes
        self.settings = settings
        self.scale = scale or 1.
        self.calibrated = scale is not None
        self.roundtrip = roundtrip
        self.active = True
        self.progress = 0.
        self.last_time = None
        self.last_point = None
        self.speed = 0.
        self.spoken.clear()
        self.cues = cues_for(route, notes, settings['mode'], self.scale)
        self.lap = 0
        self.leg = '去程'
        self.offroute_count = 0
        self.arrival_count = 0

    def stop(self):
        self.active = False
        self.last_time = None
        self.last_point = None

    def lost(self):
        self.last_time = None
        self.last_point = None
        self.speed = 0.

    def update(self, point, now):
        if not self.active or not self.route:
            return None
        old_time, old_point = self.last_time, self.last_point
        dt = now-old_time if old_time is not None else None
        if dt and dt > 0 and old_point is not None:
            v = distance(point, old_point)*self.scale/dt
            if v < 85:
                self.speed = self.speed*.65 + v*.35
        self.last_time, self.last_point = now, point
        # Constrain progress around the last segment to avoid jumping to a later
        # leg at a crossing or an out-and-back overlap.
        upper = math.inf if old_time is None else self.progress + max(45/self.scale, (self.speed*(dt or 1)+60)/self.scale)
        projection = nearest_on_route(point, self.route.points, max(0,self.progress-25/self.scale), upper)
        if projection is None:
            return {'state':'offroute','text':'偏离路线，请检查定位或重新规划','speech':None}
        gap, s, _, _ = projection
        if gap*self.scale > self.settings['offroute_m']:
            self.offroute_count += 1
            return {'state':'offroute','text':'偏离路线，正在重算' if self.offroute_count >= 3 else '偏离路线','speech':None,'replan':self.offroute_count >= 3}
        self.offroute_count = 0
        self.progress = max(self.progress, s)
        remaining = max(0., (self.route.length-self.progress)*self.scale)
        threshold = self.settings['arrival_m']
        at_end = remaining <= threshold and distance(point, self.route.points[-1])*self.scale <= threshold
        self.arrival_count = self.arrival_count+1 if at_end else 0
        if self.arrival_count >= 2:
            self.arrival_count = 0
            if self.roundtrip:
                r = self.route
                self.route = r.reversed()
                self.lap += 1
                self.leg = '返程' if self.lap%2 else '去程'
                self.cues = cues_for(self.route, self.notes, self.settings['mode'], self.scale)
                self.progress = 0.
                self.spoken.clear()
                self.last_time = None
                return {'state':'turnaround','text':f'已到达，开始{self.leg}','speech':f'已到达，请安全掉头，开始{self.leg}','remaining':self.route.length*self.scale}
            self.active = False
            return {'state':'arrived','text':'已到达目的地','speech':'已到达目的地','remaining':0}
        candidates = [c for c in self.cues if c.at >= self.progress-6/self.scale]
        cue = candidates[0] if candidates else self.cues[-1]
        to_cue = max(0., (cue.at-self.progress)*self.scale)
        mode=self.settings['mode']
        prefix='wrc_' if mode=='wrc' else ''
        pending=[c for c in candidates if c.id not in self.spoken]
        announcement=(pending[0] if pending else None) if mode=='wrc' else cue
        speech_distance=max(0.,(announcement.at-self.progress)*self.scale) if announcement else math.inf
        lead=((announcement.lead_m if announcement else 0) or self.settings.get(prefix+'lead_m',self.settings['lead_m']))+self.speed*self.settings.get(prefix+'lead_s',self.settings['lead_s'])
        speech = None
        if announcement and announcement.id not in self.spoken and speech_distance <= lead:
            self.spoken.add(announcement.id)
            text=cue_text(announcement,mode,spoken=True)
            if mode=='normal':
                speech=f'前方{distance_text(speech_distance,self.calibrated)}，{text}' if speech_distance>=15 else text
            else:
                speech=(distance_text(speech_distance,self.calibrated)+'，' if speech_distance>=15 else '')+text
                previous=announcement
                for following in pending[1:3]:
                    gap=(following.at-previous.at)*self.scale
                    if following.kind=='arrival' or gap>self.settings.get('wrc_chain_m',60):break
                    if following.id not in self.spoken:
                        speech+=('，接，' if gap<25 else '，'+distance_text(gap,self.calibrated)+'，')+cue_text(following,mode,spoken=True)
                        self.spoken.add(following.id)
                    previous=following
        elif mode=='normal' and to_cue>lead and 'along-'+cue.id not in self.spoken:
            self.spoken.add('along-'+cue.id)
            speech='沿当前道路行驶'+distance_text(to_cue,self.calibrated)
        text=cue_text(cue,mode)
        if mode=='normal' and to_cue>lead:text='沿当前道路行驶'
        return {'state':'navigating','cue':cue,'text':text,'next_text':cue_text(cue,mode),
                'distance':to_cue,'remaining':remaining,'speech':speech,'speed':self.speed,
                'inferred':cue.inferred,'leg':self.leg,'lap':self.lap,
                'upcoming':[{'cue':c,'distance':max(0,(c.at-self.progress)*self.scale)} for c in candidates[:3]]}
