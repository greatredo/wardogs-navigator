import pytest
from wardogs_nav.routing import Route
from wardogs_nav.navigation import Navigator,cues_for,cue_text
from wardogs_nav.model import default_settings


def route(points):
    from wardogs_nav.routing import distance
    return Route(points,['major']*(len(points)-1),['r']*(len(points)-1),sum(distance(a,b) for a,b in zip(points,points[1:])),[0,0],0)


def test_arrival_requires_two_end_fixes_and_roundtrip_reverses():
    nav=Navigator();settings=default_settings();settings['arrival_m']=5
    nav.start(route([[0,0],[100,0]]),[],settings,1,True)
    nav.update([0,0],0);nav.update([50,0],1)
    assert nav.update([99,0],2)['state']=='navigating'
    data=nav.update([100,0],3);assert data['state']=='turnaround'
    assert nav.route.points==[[100,0],[0,0]] and nav.lap==1
    nav.update([100,0],4);nav.update([50,0],5);nav.update([0,0],6)
    assert nav.update([0,0],7)['state']=='turnaround' and nav.lap==2


def test_no_arrival_when_off_road_near_route_end():
    nav=Navigator();settings=default_settings();settings['arrival_m']=5
    nav.start(route([[0,0],[100,0]]),[],settings,1)
    for t in range(3):assert nav.update([100,50],t)['state']!='arrived'


def test_speech_is_deduplicated_and_lead_adjustable():
    nav=Navigator();settings=default_settings();settings.update(lead_m=25,lead_s=0,arrival_m=5)
    r=route([[0,100],[0,0],[100,0]]);r.junctions=[dict(at=100,delta=90)]
    nav.start(r,[],settings,1)
    assert nav.update([0,60],0)['speech']=='沿当前道路行驶60米'
    assert nav.update([0,20],1)['speech']=='前方20米，路口右转'
    assert nav.update([0,19],2)['speech'] is None
    nav.stop();assert nav.update([0,0],3) is None


def test_normal_curves_silent_but_physical_junctions_have_turn_and_straight():
    from wardogs_nav.routing import plan
    def road(id,points):return dict(id=id,points=points,kind='major',confirmed=True)
    main=road('main',[[0,100],[0,50],[0,0],[100,0]])
    smooth=plan([main],[[0,100],[100,0]],['major'])
    assert [c.kind for c in cues_for(smooth,[],'normal')]==['arrival']
    assert any(c.kind=='square_right' for c in cues_for(smooth,[],'wrc'))
    with_junctions=plan([main,road('side',[[0,50],[70,50]]),road('out',[[0,0],[-50,0]])],[[0,100],[100,0]],['major'])
    assert [c.kind for c in cues_for(with_junctions,[],'normal')]==['straight','right','arrival']
    # Road-ID changes at a degree-two join are still the same continuous road.
    split=plan([road('a',[[0,100],[0,0]]),road('b',[[0,0],[100,0]])],[[0,100],[100,0]],['major'])
    assert [c.kind for c in cues_for(split,[],'normal')]==['arrival']


def test_wrc_smooth_curve_is_one_note_and_grade_density_independent():
    import math
    def arc(step):return route([[100+100*math.cos(math.radians(i)),100+100*math.sin(math.radians(i))] for i in range(0,91,step)])
    a=[c for c in cues_for(arc(1),[],'wrc') if c.kind!='arrival']
    b=[c for c in cues_for(arc(5),[],'wrc') if c.kind!='arrival']
    assert len(a)==len(b)==1
    assert a[0].kind==b[0].kind=='right' and a[0].grade==b[0].grade


def test_wrc_manual_brake_square_chain_modifiers_and_separate_timing():
    nav=Navigator();settings=default_settings()
    settings.update(mode='wrc',lead_m=5,lead_s=0,wrc_lead_m=70,wrc_lead_s=0,wrc_chain_m=60,arrival_m=5)
    notes=[dict(id='brake',point=[80,0],type='hard_brake',grade=1,bearing=90,direction='both'),
           dict(id='left',point=[100,0],type='left',grade=3,bearing=90,direction='both',modifiers=['dont_cut']),
           dict(id='square',point=[130,0],type='square_right',grade=1,bearing=90,direction='both')]
    nav.start(route([[0,0],[300,0]]),notes,settings,1)
    assert nav.update([0,0],0)['speech'] is None
    speech=nav.update([20,0],1)['speech']
    assert '急刹车' in speech and '左三，别切' in speech and '右直角' in speech
    assert nav.update([21,0],2)['speech'] is None
    assert nav.update([100,0],5)['speech'] is None


def test_after_junction_speaks_next_road_distance_and_reverse_turn():
    r=route([[0,100],[0,0],[400,0]]);r.junctions=[dict(at=100,delta=90)]
    nav=Navigator();settings=default_settings();settings.update(lead_m=30,lead_s=0)
    nav.start(r,[],settings,1)
    nav.update([0,20],0)
    assert nav.update([15,0],1)['speech']=='沿当前道路行驶380米'
    assert cues_for(r.reversed(),[],'normal')[0].kind=='left'


def test_wrc_next_unspoken_note_can_play_before_passing_previous():
    settings=default_settings();settings.update(mode='wrc',wrc_lead_m=100,wrc_lead_s=0,wrc_chain_m=0)
    notes=[dict(id=id,point=[x,0],type=kind,grade=6,bearing=90,direction='both',lead_m=lead)
           for id,x,kind,lead in [('one',200,'left',200),('two',240,'right',220)]]
    nav=Navigator();nav.start(route([[0,0],[500,0]]),notes,settings,1)
    assert '左六' in nav.update([0,0],0)['speech']
    assert nav.update([1,0],1)['speech'] is None
    assert '右六' in nav.update([25,0],2)['speech']


def test_integer_timing_controls_survive_restart(tmp_path,monkeypatch):
    from wardogs_nav.model import atomic_json,load_settings
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path))
    settings=default_settings();settings.update(lead_m=230,wrc_lead_m=320,wrc_chain_m=75,wrc_lead_s=6.5)
    atomic_json(tmp_path/'settings.json',settings)
    loaded=load_settings()
    assert loaded['lead_m']==230 and loaded['wrc_lead_m']==320 and loaded['wrc_chain_m']==75 and loaded['wrc_lead_s']==6.5


def test_manual_wrc_grade_overrides_estimate_and_reverses():
    r=route([[0,100],[0,0],[100,0]])
    note=dict(id='n',point=[0,0],type='right',grade=3,bearing=0,direction='both',lead_m=180,text='右三，别切',reverse_text='左三，别切')
    forward=[c for c in cues_for(r,[note],'wrc') if c.id=='n'][0]
    reverse=[c for c in cues_for(route(list(reversed(r.points))),[note],'wrc') if c.id=='n'][0]
    assert forward.kind=='right' and forward.grade==3 and not forward.inferred
    assert reverse.kind=='left' and reverse.text=='左三，别切'
    assert forward.lead_m==180


def test_directional_note_only_plays_in_requested_direction():
    note=dict(id='n',point=[50,0],type='caution',grade=4,bearing=90,direction='forward')
    assert any(c.id=='n' for c in cues_for(route([[0,0],[100,0]]),[note],'wrc'))
    assert not any(c.id=='n' for c in cues_for(route([[100,0],[0,0]]),[note],'wrc'))


def test_lost_fix_does_not_advance_or_retain_speed():
    nav=Navigator();nav.start(route([[0,0],[100,0]]),[],default_settings(),1)
    nav.update([0,0],0);nav.update([20,0],1);progress=nav.progress;nav.lost()
    assert nav.progress==progress and nav.speed==0 and nav.last_point is None


def test_normal_nearby_junctions_use_v062_individual_speech():
    r=route([[0,0],[200,0],[300,0],[300,300]])
    r.junctions=[dict(at=200,delta=0),dict(at=300,delta=90)]
    settings=default_settings();settings.update(lead_m=150,lead_s=0)
    nav=Navigator();nav.start(r,[],settings,1)
    assert nav.update([100,0],0)['speech']=='前方100米，路口直行'
    assert nav.update([160,0],1)['speech'] is None
    assert nav.update([220,0],2)['speech']=='前方80米，路口右转'
    assert nav.update([260,0],3)['speech'] is None


@pytest.mark.parametrize('mode',['normal','wrc'])
def test_wrong_way_warns_once_and_recovers_without_losing_trip(mode):
    nav=Navigator();settings=default_settings();settings['mode']=mode
    r=route([[0,0],[1000,0]]);nav.start(r,[],settings,1,True)
    nav.lap=1;nav.leg='返程'
    assert nav.update([500,0],0)['state']=='navigating'
    assert nav.update([490,0],1)['state']=='navigating'
    data=nav.update([480,0],2)
    assert data['state']=='wrongway' and data['cue'].kind=='uturn' and '安全位置掉头' in data['speech']
    assert nav.update([470,0],3)['speech'] is None
    assert nav.update([480,0],4)['state']=='wrongway'
    assert nav.update([490,0],5)['state']=='navigating'
    assert nav.active and nav.roundtrip and nav.route is r and nav.lap==1 and nav.goal==[1000,0]


def test_wrong_way_ignores_jitter_brief_reversing_gaps_and_offroad():
    nav=Navigator();settings=default_settings();r=route([[0,0],[1000,0]])
    for samples in [[(500,0),(498,1),(501,2),(497,3),(502,4)],
                    [(500,0),(490,1),(500,2),(510,3)],
                    [(500,0),(480,5),(450,10)]]:
        nav.start(r,[],settings,1)
        for x,t in samples:assert nav.update([x,0],t)['state']!='wrongway'
    nav.start(r,[],settings,1)
    for t in range(4):assert nav.update([500-t*10,60],t,60)['state']=='waiting_road'
    settings['wrong_way_alert']=False;nav.start(r,[],settings,1)
    for t in range(4):assert nav.update([500-t*10,0],t)['state']!='wrongway'


def test_following_hairpin_is_not_wrong_way():
    r=route([[0,0],[100,0],[100,30],[0,30]])
    nav=Navigator();nav.start(r,[],default_settings(),1)
    for t,p in enumerate([[60,0],[80,0],[100,0],[100,15],[100,30],[80,30],[60,30]]):
        assert nav.update(p,t)['state']!='wrongway'


def test_starting_in_opposite_direction_warns_behind_first_route_point():
    nav=Navigator();nav.start(route([[500,100],[1500,100]]),[],default_settings(),1)
    nav.update([500,100],0,0)
    assert nav.update([460,100],1,0)['state']=='navigating'
    data=nav.update([420,100],2,0)
    assert data['state']=='wrongway' and data['remaining']==1000 and nav.progress==0
    assert nav.update([400,100],3,0)['speech'] is None
    assert nav.update([450,100],4,0)['state']!='wrongway'


def test_offroute_waits_for_three_fixes():
    nav=Navigator();settings=default_settings();settings['offroute_m']=20
    nav.start(route([[0,0],[100,0]]),[],settings,1)
    assert not nav.update([50,40],0).get('replan')
    assert not nav.update([50,40],1).get('replan')
    assert nav.update([50,40],2)['replan']


def test_arrival_uses_actual_goal_before_road_progress_or_offroad_wait():
    nav=Navigator();settings=default_settings();settings['arrival_m']=40
    nav.start(route([[0,0],[0,200],[200,200],[200,0]]),[],settings,1,goal=[200,35])
    nav.update([0,0],0,0)
    nav.update([180,40],1,40)
    assert nav.update([180,40],2,40)['state']=='arrived'
    assert not nav.active
    nav.start(route([[0,0],[200,0]]),[],settings,1,goal=[200,80])
    for t in range(3):assert nav.update([200,0],t,0)['state']!='arrived'


def test_offroad_wait_preserves_trip_then_replans_once_near_road():
    nav=Navigator();settings=default_settings();settings['arrival_m']=5
    nav.start(route([[0,0],[500,0]]),[],settings,1,True)
    nav.lap=1;nav.leg='返程'
    nav.update([10,0],0,0);progress=nav.progress
    for t in range(1,12):
        data=nav.update([100,70],t,70)
        assert data['text']=='请返回道路' and not data['replan'] and data['speech'] is None
    assert nav.active and nav.progress==progress and nav.lap==1 and nav.leg=='返程'
    assert not nav.update([100,27],12,27)['replan']
    assert nav.update([100,10],13,10)['replan']
    nav.defer_replan([100,10],13)
    for t in range(14,30):assert not nav.update([100,10],t,10)['replan']
    assert nav.update([150,10],30,10)['replan']


def test_overlapping_arrival_areas_do_not_flip_legs_while_parked():
    nav=Navigator();settings=default_settings();settings['arrival_m']=60
    nav.start(route([[0,0],[100,0]]),[],settings,1,True)
    nav.update([50,0],0);assert nav.update([50,0],1)['state']=='turnaround'
    for t in range(2,10):assert nav.update([50,0],t)['state']!='turnaround'
    assert nav.lap==1
    nav.update([0,0],10);assert nav.update([0,0],11)['state']=='turnaround'


def test_road_distance_honors_enabled_roads_avoidance_and_private_route():
    from wardogs_nav.routing import distance_to_roads
    roads=[dict(kind='major',points=[[0,0],[100,0]]),dict(kind='offroad',points=[[0,50],[100,50]])]
    assert distance_to_roads([50,50],roads,['major'])==50
    assert distance_to_roads([50,50],roads,['major','offroad'])==0
    assert distance_to_roads([50,50],roads,['major'],extra_route=route([[0,50],[100,50]]))==0
    assert distance_to_roads([50,0],roads,['major'],[dict(point=[50,0],radius=10)])==float('inf')
