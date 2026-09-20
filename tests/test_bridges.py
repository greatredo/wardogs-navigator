from copy import deepcopy
import pytest
from wardogs_nav.routing import plan,RouteError
from wardogs_nav.model import validate_project,atomic_json,read_project
from wardogs_nav.library import saved_route,follow_saved,supplement_roads,library_payload,merge_library
from wardogs_nav.navigation import cues_for

POLICY=dict(allowed=['major','minor','offroad'],confirmed_only=False)

def road(id,points,**options):
    return dict(id=id,name=id,kind='major',points=points,confirmed=True,**options)

def project(roads):
    return validate_project(dict(schema=1,map='ozeti',roads=roads,notes=[],avoid=[],waypoints=[],destinations=[],destination=None,roundtrip=False))

@pytest.fixture
def crossing():
    return [road('bridge',[[100,300],[300,300],[500,300]],bridge=True),
            road('ground',[[300,100],[300,300],[300,500]])]

def test_bridge_crossing_cannot_turn_even_at_shared_vertex(crossing):
    with pytest.raises(RouteError,match='不连通'):
        plan(crossing,[[100,300],[300,500]],['major'])
    for anchors in ([[100,300],[500,300]],[[300,100],[300,500]]):
        r=plan(crossing,anchors,['major'])
        assert r.length==400 and not r.junctions
        assert [c.kind for c in cues_for(r,[],'normal')]==['arrival']

def test_ground_junction_under_bridge_does_not_create_bridge_cue(crossing):
    crossing.append(road('ground-side',[[300,300],[400,400]]))
    assert not plan(crossing,[[100,300],[500,300]],['major']).junctions
    assert plan(crossing,[[300,100],[300,500]],['major']).junctions

def test_segmented_bridge_join_is_not_an_automatic_ground_connection(crossing):
    crossing[0]['points']=[[100,300],[300,300]]
    crossing.append(road('bridge-two',[[300,300],[500,300]],bridge=True))
    assert plan(crossing,[[100,300],[500,300]],['major']).length==400
    with pytest.raises(RouteError):plan(crossing,[[100,300],[300,500]],['major'])

def test_explicit_bridgehead_connects_and_avoids_shortcut(crossing):
    crossing[0]['bridge_start']=True
    crossing.append(road('approach',[[300,100],[100,100],[100,300]]))
    r=plan(crossing,[[300,100],[400,300]],['major'])
    assert (100,300) in r.points and r.length==700
    assert r.reversed().bridges==list(reversed(r.bridges))
    assert r.reversed().bridge_connections==r.bridge_connections
    crossing[0]['bridge_start']=False
    with pytest.raises(RouteError):plan(crossing,[[300,100],[400,300]],['major'])

def test_bridgehead_can_join_ground_segment_interior():
    roads=[road('ground',[[100,100],[100,500]]),road('bridge',[[100,300],[500,300]],bridge=True,bridge_start=True)]
    assert plan(roads,[[100,100],[500,300]],['major']).length==600

@pytest.mark.parametrize('reverse_order',[False,True])
def test_waypoint_at_crossing_cannot_teleport_between_levels(crossing,reverse_order):
    if reverse_order:crossing.reverse()
    with pytest.raises(RouteError):plan(crossing,[[100,300],[300,300],[300,500]],['major'])

def test_favourite_rejects_existing_impossible_turn(crossing):
    saved=dict(id='fav',name='错误转弯',points=[[100,300],[300,300],[300,500]],kinds=['major','major'])
    before=deepcopy(crossing)
    assert supplement_roads(crossing,saved)==0
    with pytest.raises(RouteError,match='不能直接转弯'):follow_saved(crossing,saved,POLICY)
    assert crossing==before

def test_saved_bridge_keeps_layer_on_import_and_reverse(crossing,tmp_path):
    r=plan(crossing,[[100,300],[500,300]],['major'])
    saved=saved_route('过桥',r)
    p=project(crossing);p['route_library']=[saved]
    path=tmp_path/'桥梁收藏.json';atomic_json(path,library_payload(p,'routes'))
    incoming=read_project(path)
    target=project([crossing[1]])
    merged,count,added=merge_library(target,incoming,'routes')
    assert count==1 and added>0
    assert any(r.get('bridge') for r in merged['roads'])
    with pytest.raises(RouteError):plan(merged['roads'],[[100,300],[300,500]],['major'])
    follow=follow_saved(merged['roads'],merged['route_library'][0],POLICY,reverse=True)
    assert follow.length==pytest.approx(400) and all(follow.bridges)

def test_marking_existing_road_as_bridge_does_not_clone_ground_favourite(crossing):
    crossing[0]['bridge']=False
    saved=saved_route('旧路径',plan(crossing,[[100,300],[300,500]],['major']))
    crossing[0]['bridge']=True
    assert supplement_roads(crossing,saved)==0 and len(crossing)==2
    with pytest.raises(RouteError,match='不能直接转弯'):follow_saved(crossing,saved,POLICY)

def test_export_refreshes_legacy_favourite_bridge_layer(crossing):
    legacy=dict(id='old',name='旧过桥路径',points=[[100,300],[500,300]],kinds=['major'])
    p=project(crossing);p['route_library']=[legacy]
    exported=library_payload(p,'routes')['route_library'][0]
    assert exported['bridges'] and all(exported['bridges'])
    assert p['route_library'][0]==legacy
    restored=[];supplement_roads(restored,exported)
    assert all(r.get('bridge') for r in restored)

def test_bridgeheads_survive_portable_favourite_reconstruction():
    roads=[road('in',[[50,100],[100,100]]),
           road('deck',[[100,100],[200,100],[300,100]],bridge=True,bridge_start=True,bridge_end=True),
           road('out',[[300,100],[350,100]])]
    saved=saved_route('桥头',plan(roads,[[50,100],[350,100]],['major']))
    restored=[];supplement_roads(restored,saved)
    result=plan(restored,[[50,100],[350,100]],['major'])
    assert result.length==pytest.approx(300)
    deck=next(r for r in restored if r.get('bridge'))
    assert deck['bridge_start'] and deck['bridge_end']

def test_snapped_mid_bridge_connection_survives_export():
    roads=[road('ground',[[300,50],[300,100],[300,150]]),
           road('a',[[100,100],[300.4,100]],bridge=True,bridge_end=True),
           road('b',[[300.4,100],[500,100]],bridge=True)]
    saved=saved_route('中间接地',plan(roads,[[100,100],[500,100]],['major']))
    restored=[deepcopy(roads[0])];supplement_roads(restored,saved)
    assert plan(restored,[[100,100],[300,150]],['major']).length==pytest.approx(250,abs=2)

def test_favourite_connector_must_use_bridgehead_at_overlapping_projection(crossing):
    saved=saved_route('过桥',plan(crossing,[[100,300],[500,300]],['major']))
    with pytest.raises(RouteError):follow_saved(crossing,saved,POLICY,start=[300,150])
    crossing[0]['bridge_start']=True
    crossing.append(road('approach',[[300,100],[100,100],[100,300]]))
    joined=follow_saved(crossing,saved,POLICY,start=[300,150])
    assert (100,300) in joined.points and joined.length>600

def test_road_bridge_flags_survive_utf8_roundtrip_and_validation(crossing,tmp_path):
    crossing[0].update(bridge_start=True,bridge_end=False)
    p=project(crossing);path=tmp_path/'桥梁路网.json'
    atomic_json(path,library_payload(p,'roads'));loaded=read_project(path)
    assert loaded['roads']==p['roads']
    assert not loaded['roads'][1].get('bridge',False)
    loaded['roads'][0]['bridge']='yes'
    with pytest.raises(ValueError,match='桥梁'):validate_project(loaded)

def test_ordinary_road_import_preserves_legacy_record_without_duplicates(crossing):
    p=project([crossing[1]]);before=deepcopy(p['roads'])
    incoming=library_payload(p,'roads')
    incoming['roads'][0].update(bridge=False,bridge_start=False,bridge_end=False)
    merged,count,added=merge_library(p,incoming,'roads')
    assert count==added==0 and merged['roads']==before
