from copy import deepcopy
import pytest
from wardogs_nav.library import supplement_roads,follow_saved,library_payload,merge_library
from wardogs_nav.routing import plan,blocked,distance
from wardogs_nav.model import validate_project,atomic_json,read_project


def road(id,points,kind='major',confirmed=True):
    return dict(id=id,name=id,points=points,kind=kind,confirmed=confirmed)


def favorite(points,kinds=None):
    return dict(id='fav',name='河边运补线',points=points,kinds=kinds or ['major']*(len(points)-1))


def base(roads=None):
    return validate_project(dict(schema=1,map='ozeti',roads=roads or [],notes=[],avoid=[],waypoints=[],
                                 destinations=[],destination=None,roundtrip=False,meters_per_pixel=5))


policy=dict(allowed=['major','minor','offroad'],confirmed_only=False)


def test_supplement_only_internal_gap_and_idempotent():
    roads=[road('before',[[0,0],[40,0]]),road('after',[[60,0],[100,0]])]
    saved=favorite([[0,0],[100,0]],['offroad'])
    assert supplement_roads(roads,saved)==1
    assert roads[-1]['kind']=='offroad' and not roads[-1]['confirmed']
    assert 35<=roads[-1]['points'][0][0]<=42 and 58<=roads[-1]['points'][-1][0]<=65
    assert supplement_roads(roads,saved)==0
    route=plan(roads,[[0,0],[100,0]],policy['allowed'])
    assert route.length==pytest.approx(100,abs=2)


def test_perpendicular_crossing_is_not_road_coverage():
    roads=[road('cross',[[50,0],[50,100]])]
    saved=favorite([[0,50],[100,50]],['minor'])
    assert supplement_roads(roads,saved)==1
    assert roads[-1]['points']==[[0,50],[100,50]]


def test_saved_route_keeps_detour_even_when_shortcut_available_and_can_reverse():
    roads=[road('long',[[0,0],[0,100],[100,100],[100,0]]),road('short',[[0,0],[100,0]])]
    saved=favorite([[0,0],[0,100],[100,100],[100,0]])
    followed=follow_saved(roads,saved,policy)
    assert followed.length==pytest.approx(300)
    assert plan(roads,[[0,0],[100,0]],policy['allowed']).length==100
    reverse=follow_saved(roads,saved,policy,reverse=True)
    assert reverse.points==list(reversed(followed.points))
    part=follow_saved(roads,saved,policy,start=[0,40])
    assert part.length==pytest.approx(260)


def test_saved_route_missing_road_type_and_confirmed_are_hard_constraints():
    roads=[];saved=favorite([[0,0],[100,0]],['offroad']);supplement_roads(roads,saved)
    with pytest.raises(ValueError,match='未允许'):follow_saved(roads,saved,dict(allowed=['major'],confirmed_only=False))
    with pytest.raises(ValueError,match='未实测'):follow_saved(roads,saved,dict(allowed=['offroad'],confirmed_only=True))


def test_saved_local_danger_detour_keeps_outer_sections():
    roads=[road('main',[[0,50],[200,50]]),road('detour',[[60,50],[60,90],[140,90],[140,50]])]
    saved=favorite([[0,50],[200,50]])
    zone=dict(shape='rect',point=[100,50],width=20,height=20)
    followed=follow_saved(roads,saved,policy,[zone])
    assert followed.length==pytest.approx(280,abs=2)
    assert followed.points[0]==(0,50) or followed.points[0]==[0,50]
    assert distance(followed.points[-1],[200,50])<1
    assert all(not blocked(a,b,zone) for a,b in zip(followed.points,followed.points[1:]))
    with pytest.raises(ValueError,match='绕行道路'):follow_saved(roads[:1],saved,policy,[zone])


def test_utf8_library_merge_preserves_other_content_and_repeated_import(tmp_path):
    project=base([road('r',[[0,0],[100,0]])]);project['destination']=[25,30]
    project['avoid']=[dict(shape='rect',point=[500,500],width=10,height=10)]
    imported=base();imported['route_library']=[favorite([[200,200],[300,200]],['minor'])]
    path=tmp_path/'中文收藏.json';atomic_json(path,library_payload(imported,'routes'))
    merged,count,added=merge_library(project,read_project(path),'routes')
    assert count==1 and added==1 and merged['destination']==[25,30] and merged['avoid']==project['avoid']
    twice,count,added=merge_library(merged,read_project(path),'routes')
    assert count==added==0 and twice==merged
    exported=library_payload(merged,'roads')
    assert exported['roads']==merged['roads'] and not exported['route_library']
    invalid=deepcopy(imported);invalid['route_library'][0]['kinds']=[]
    with pytest.raises(ValueError):merge_library(project,invalid,'routes')
    assert len(project['roads'])==1 and not project['route_library']
