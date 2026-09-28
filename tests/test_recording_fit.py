from copy import deepcopy
import pytest
from wardogs_nav.recording import add_recorded_roads,RoadRecorder
from wardogs_nav.routing import cumulative,plan,RouteError


def road(points,**values):
    return dict(id=values.pop('id','old'),name='已有小路',kind='minor',confirmed=True,points=points,**values)


def fitted(roads,traces,**values):
    return add_recorded_roads(roads,traces,snap_to_roads=True,snap_distance_m=10,**values)


@pytest.mark.parametrize('scale',[1.,5.35])
def test_close_parallel_trace_is_fitted_in_meters(scale):
    old=[road([[0,100],[150,100]])]
    trace=[[[0,100+9/scale],[150,100+9/scale]]]
    result,count=fitted(old,trace,scale=scale)
    assert result==old and count==0
    separate,count=fitted(old,[[[0,100+12/scale],[150,100+12/scale]]],scale=scale)
    assert count>0 and len(separate)>1


def test_mean_is_local_and_uniformly_sampled():
    old=[road([[0,100],[150,100]])]
    # Many samples near the road cannot hide the far middle span.
    trace=[[x,105] for x in range(31)]+[[60,140],[90,140],[120,105],[150,105]]
    result,count=fitted(old,[trace])
    assert count>0 and result[0]==old[0]
    assert any(any(p[1]>=139 for p in r['points']) for r in result[1:])
    route=plan(result,[[0,100],[75,140]],['minor','offroad'])
    assert route.snap_distances[-1]<1


def test_mean_does_not_require_every_sample_within_threshold():
    old=[road([[0,100],[100,100]])]
    # This short stretch has mean offset 8, although its last sample is at 12.
    result,count=fitted(old,[[[10,104],[25,112]]])
    assert count==0 and result==old


def test_ends_outside_overlap_stay_new_and_connected():
    old=[road([[30,100],[90,100]])]
    result,count=fitted(old,[[[0,106],[120,106]]])
    assert count==2 and len(result)==3
    route=plan(result,[[0,106],[120,106]],['minor','offroad'])
    assert route.length==pytest.approx(132) and 'minor' in route.kinds


def test_perpendicular_crossing_and_bridge_are_not_fitted():
    old=[road([[50,50],[50,150]])]
    result,count=fitted(old,[[[10,100],[100,100]]])
    assert count==2 and plan(result,[[10,100],[50,150]],['minor','offroad']).length==90
    bridge=[road([[0,100],[100,100]],bridge=True)]
    result,count=fitted(bridge,[[[0,104],[100,104]]],merge_shortest=True)
    assert count==1 and result[0]==bridge[0]
    with pytest.raises(RouteError):plan(result,[[0,100],[100,104]],['minor','offroad'])


@pytest.mark.parametrize('reverse',[False,True])
def test_shortest_merge_preserves_properties_and_road_id(reverse):
    old=[road([[0,100],[25,108],[50,100],[75,108],[100,100]],note='保留备注')]
    before=deepcopy(old);trace=[[0,100],[100,100]]
    result,count=fitted(old,[list(reversed(trace)) if reverse else trace],merge_shortest=True)
    assert count==1 and len(result)==1 and old==before
    assert cumulative(result[0]['points'])[-1]<cumulative(old[0]['points'])[-1]
    assert {k:v for k,v in result[0].items() if k!='points'}=={k:v for k,v in old[0].items() if k!='points'}
    assert result[0]['points'][0]==old[0]['points'][0] and result[0]['points'][-1]==old[0]['points'][-1]


def test_shorter_existing_shape_wins_and_disabled_merge_keeps_shape():
    straight=[road([[0,100],[100,100]])]
    trace=[[0,100],[25,108],[50,100],[75,108],[100,100]]
    result,count=fitted(straight,[trace],merge_shortest=True)
    assert result==straight and count==0
    winding=[road(trace)]
    result,count=fitted(winding,[[[0,100],[100,100]]])
    assert result==winding and count==0
    result,count=add_recorded_roads(winding,[[[0,100],[100,100]]],snap_to_roads=False,merge_shortest=True)
    assert result[0]==winding[0]


def test_merge_keeps_branch_junction_fixed_and_connected():
    old=[road([[0,100],[25,108],[50,100],[75,108],[100,100]]),
         road([[50,100],[50,150]],id='branch')]
    result,count=fitted(old,[[[0,100],[100,100]]],merge_shortest=True)
    assert count==1 and [50,100] in result[0]['points'] and result[1]==old[1]
    assert cumulative(result[0]['points'])[-1]<cumulative(old[0]['points'])[-1]
    assert plan(result,[[0,100],[50,150]],['minor']).length==pytest.approx(100)


def test_automatic_merge_still_requires_independent_passes():
    roads=[road([[0,100],[25,108],[50,100],[75,108],[100,100]])]
    rec=RoadRecorder();rec.set_roads(roads);rec.merge_shortest=True
    for iteration,xs in enumerate((range(0,101,5),range(100,-1,-5),range(0,101,5))):
        for i,x in enumerate(xs):rec.feed([x,100],iteration*100+i*.5,True)
        rec.disconnect()
        if iteration<2:assert not rec.ready(3)
    ready=rec.ready(3);assert ready
    result,count=fitted(roads,[u['points'] for u in ready],source='auto',merge_shortest=True)
    assert count>0 and len(result)==1
    assert cumulative(result[0]['points'])[-1]<cumulative(roads[0]['points'])[-1]


def test_merge_preserves_junction_away_from_the_recorded_centerline():
    old=[road([[0,100],[15,116],[35,116],[50,106],[65,116],[85,116],[100,100]]),
         road([[50,106],[50,150]],id='branch')]
    result,count=add_recorded_roads(old,[[[0,100],[100,100]]],snap_to_roads=True,snap_distance_m=20,merge_shortest=True)
    assert count==1 and [50,106] in result[0]['points'] and result[1]==old[1]
    assert cumulative(result[0]['points'])[-1]<cumulative(old[0]['points'])[-1]
    assert plan(result,[[0,100],[50,150]],['minor']).length<110


def test_shorter_shape_connects_new_ground_crossing():
    old=[road([[0,100],[50,130],[100,100]]),road([[50,50],[50,110]],id='cross')]
    result,count=add_recorded_roads(old,[[[0,100],[100,100]]],snap_to_roads=True,snap_distance_m=30,merge_shortest=True)
    assert count==1 and [50,100] in result[0]['points']
    assert plan(result,[[0,100],[50,110]],['minor']).length==pytest.approx(60)


def test_auto_live_merge_compares_across_sample_boundaries():
    roads=[road([[0,100],[25,108],[50,100],[75,108],[100,100]])]
    original=cumulative(roads[0]['points'])[-1]
    rec=RoadRecorder();rec.set_roads(roads);rec.merge_shortest=True
    for iteration,xs in enumerate((range(0,101,5),range(100,-1,-5),range(0,101,5))):
        for i,x in enumerate(xs):
            rec.feed([x,100],iteration*100+i*.5,True)
            ready=rec.ready(3)
            if ready:
                roads,_=fitted(roads,rec.promotion_traces(ready,3),source='auto',merge_shortest=True)
                rec.promoted(ready);rec.set_roads(roads)
        rec.disconnect()
    assert len(roads)==1 and cumulative(roads[0]['points'])[-1]<original
