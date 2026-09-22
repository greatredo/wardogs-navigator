from copy import deepcopy
import pytest
from wardogs_nav.recording import RoadRecorder,add_recorded_roads
from wardogs_nav.routing import plan,RouteError,cumulative,Route
from wardogs_nav.navigation import cues_for,cue_text,Navigator
from wardogs_nav.model import default_settings


def road(points,**kw):return dict(id='existing',name='existing',kind='minor',confirmed=True,points=points,**kw)


def test_recorded_road_splits_at_ground_crossing_and_can_turn():
    old=[road([[50,50],[50,150]])];before=deepcopy(old)
    roads,count=add_recorded_roads(old,[[[10,100],[100,100]]])
    assert count==2 and old==before
    new=roads[1:]
    assert all(r['kind']=='offroad' for r in new)
    assert new[0]['points'][-1]==new[1]['points'][0]==[50,100]
    assert plan(roads,[[10,100],[50,150]],['minor','offroad']).length==90


def test_recording_skips_overlaps_and_reverse_duplicate():
    roads,count=add_recorded_roads([road([[30,100],[70,100]])],[[[10,100],[100,100]],[[100,100],[10,100]]])
    assert count==2 and len(roads)==3
    assert roads[1]['points'][-1]==[30,100] and roads[2]['points'][0]==[70,100]
    again,count=add_recorded_roads(roads,[[[10,100],[100,100]]])
    assert count==0 and again==roads


def test_recorded_crossing_below_bridge_keeps_levels_separate():
    roads,count=add_recorded_roads([road([[50,50],[50,150]],bridge=True)],[[[10,100],[100,100]]])
    assert count==1
    with pytest.raises(RouteError):plan(roads,[[10,100],[50,150]],['minor','offroad'])


def pass_line(rec,xs,t=0):
    for i,x in enumerate(xs):rec.feed([x,100],t+i*.5,True)
    rec.disconnect()


def test_auto_three_independent_passes_both_directions_and_restart():
    rec=RoadRecorder()
    pass_line(rec,range(10,121,5))
    assert rec.state['units'] and not rec.ready(3)
    restored=RoadRecorder(rec.state)
    pass_line(restored,range(120,9,-5))
    assert not restored.ready(3)
    pass_line(restored,range(10,121,5),100)
    ready=restored.ready(3)
    assert len(ready)>=3
    roads,count=add_recorded_roads([],[u['points'] for u in ready],source='auto')
    assert count==1 and cumulative(roads[0]['points'])[-1]>80
    restored.promoted(ready)
    assert not restored.ready(3)


def test_parking_jitter_does_not_vote_and_parallel_trace_is_independent():
    rec=RoadRecorder();pass_line(rec,range(10,121,5))
    counts=[u['count'] for u in rec.state['units']]
    for i in range(300):rec.feed([60+(i%3-1)*.4,100],200+i*.5,True)
    assert [u['count'] for u in rec.state['units']]==counts
    rec.disconnect()
    for i,x in enumerate(range(10,121,5)):rec.feed([x,106],400+i*.5,True)
    assert not rec.ready(2)


def test_jump_gap_and_manual_recovery_do_not_connect():
    rec=RoadRecorder();rec.start()
    rec.feed([10,100],0);rec.feed([30,100],1)
    rec.feed([500,100],1.5);rec.feed([520,100],2)
    rec.feed([550,100],10);rec.feed([570,100],11)
    roads,count=add_recorded_roads([],rec.stop())
    assert count==3 and all(cumulative(r['points'])[-1]==20 for r in roads)


def test_automatic_extension_preserves_crossroad_split():
    roads,_=add_recorded_roads([road([[50,50],[50,150]])],[[[10,100],[40,100]]],source='auto')
    roads,_=add_recorded_roads(roads,[[[40,100],[70,100]]],source='auto')
    assert len(roads)==3
    assert sorted(cumulative(r['points'])[-1] for r in roads[1:])==[20,40]


def test_automatic_live_promotion_joins_existing_roads_at_game_scale():
    roads=[road([[10,80],[10,120]]),dict(road([[110,80],[110,120]]),id='end')]
    rec=RoadRecorder(scale=5.35);rec.set_roads(roads)
    for pass_index,xs in enumerate((range(10,111,2),range(110,9,-2),range(10,111,2))):
        for i,x in enumerate(xs):
            rec.feed([x,100],pass_index*100+i*.7,True)
            ready=rec.ready(3)
            if ready:
                roads,_=add_recorded_roads(roads,[u['points'] for u in ready],5.35,'auto')
                rec.promoted(ready);rec.set_roads(roads)
        rec.disconnect()
    ready=rec.ready(3)
    roads,_=add_recorded_roads(roads,[u['points'] for u in ready],5.35,'auto')
    assert len(roads)==3
    assert plan(roads,[[10,80],[110,120]],['minor','offroad']).length==pytest.approx(140,abs=3)


@pytest.mark.parametrize('mode',['normal','wrc'])
def test_each_reentry_after_short_ordinary_road_has_offroad_cue(mode):
    points=[[0,0],[100,0],[200,0],[205,0],[300,0]]
    r=Route(points,['major','offroad','minor','offroad'],['a','b','c','d'],300,[0,0],0)
    cues=cues_for(r,[],mode)
    entries=[c for c in cues if c.enter_offroad]
    assert [c.at for c in entries]==[100,205]
    assert all('进入越野路段' in cue_text(c,mode) for c in entries)
    reversed_entries=[c for c in cues_for(r.reversed(),[],mode) if c.enter_offroad]
    assert [c.at for c in reversed_entries]==[100]


def test_left_turn_offroad_replaces_junction_text_without_duplicate():
    r=Route([[0,100],[100,100],[100,0]],['major','offroad'],['a','b'],200,[0,0],0,[dict(at=100,delta=-90)])
    cues=cues_for(r,[],'normal')
    assert len(cues)==2 and cue_text(cues[0],'normal')=='左转进入越野路段'
    nav=Navigator();settings=default_settings();settings.update(lead_m=100,lead_s=0)
    nav.start(r,[],settings,1)
    assert nav.update([0,100],0)['speech']=='前方100米，左转进入越野路段'


def test_offroad_prompts_have_local_audio_without_system_tts(tmp_path):
    from wardogs_audio.pack import DefaultVoicePack
    import wave
    pack=DefaultVoicePack()
    for i,direction in enumerate(('','直行','左转','右转','向左前方','向右前方','掉头')):
        output=tmp_path/f'{i}.wav'
        pack.render('前方100米，'+direction+'进入越野路段','zh-CN',output)
        with wave.open(str(output)) as audio:assert audio.getnframes()>audio.getframerate()


@pytest.mark.parametrize('mode',['normal','wrc'])
def test_straight_crossing_of_ordinary_road_reannounces_offroad(mode):
    roads,_=add_recorded_roads([road([[50,50],[50,150]])],[[[10,100],[100,100]]])
    route=plan(roads,[[10,100],[100,100]],['minor','offroad'])
    assert all(k=='offroad' for k in route.kinds)
    entries=[c for c in cues_for(route,[],mode) if c.enter_offroad]
    assert len(entries)==1 and entries[0].at==40
    assert '进入越野路段' in cue_text(entries[0],mode)
