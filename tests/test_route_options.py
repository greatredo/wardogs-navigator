from copy import deepcopy
import pytest
from wardogs_nav.library import (snap_saved,follow_saved,merge_library,library_payload)
from wardogs_nav.model import validate_project,atomic_json,read_project
from wardogs_nav.routing import plan,RouteError,blocked


def road(id,points,kind='major',confirmed=True):
    return dict(id=id,name=id,points=points,kind=kind,confirmed=confirmed)


def data(roads=()):
    return validate_project(dict(schema=1,map='ozeti',roads=list(roads),notes=[],avoid=[],waypoints=[],
                                 destinations=[],destination=None,roundtrip=False,meters_per_pixel=5))


def saved(points,kinds=None,**options):
    return dict(id='favorite',name='精确保留的收藏',points=points,kinds=kinds or ['major']*(len(points)-1),**options)


POLICY=dict(allowed=['major','minor','offroad'],confirmed_only=False)


def test_coarse_controls_follow_connected_roads_and_keep_types_and_full_geometry():
    roads=[road('south',[[100,100],[100,300],[300,300]],'minor'),road('east',[[300,300],[300,100]])]
    sketch=saved([[105,105],[295,295],[295,105]])
    original=deepcopy(sketch);matched=snap_saved(roads,sketch,POLICY)
    assert matched['control_points']==original['points'] and sketch==original
    assert [100,300] in matched['points'] and [300,300] in matched['points']
    assert {'minor','major'}==set(matched['kinds'])
    assert matched['snap_to_roads'] and not matched['build_roads']
    assert all(blocked(p,p,dict(shape='rect',point=[200,200],width=5,height=5)) is False for p in matched['points'])
    assert follow_saved(roads,matched,POLICY).length>570
    with pytest.raises(RouteError):snap_saved(roads,sketch,dict(allowed=['major'],confirmed_only=False))


def test_snap_obeys_danger_and_does_not_bridge_disconnected_roads():
    roads=[road('main',[[100,100],[300,100]]),road('detour',[[150,100],[150,200],[250,200],[250,100]])]
    zone=dict(shape='rect',point=[200,100],width=20,height=20)
    matched=snap_saved(roads,saved([[100,105],[300,105]]),POLICY,[zone])
    assert all(not blocked(a,b,zone) for a,b in zip(matched['points'],matched['points'][1:]))
    disconnected=[road('left',[[100,100],[150,100]]),road('right',[[250,100],[300,100]])]
    with pytest.raises(RouteError,match='不连通'):snap_saved(disconnected,saved([[100,105],[300,105]]),POLICY)


def test_import_no_roads_keeps_private_navigation_reverse_and_hard_constraints(tmp_path):
    current=data();incoming=data()
    incoming['route_library']=[saved([[100,100],[100,200],[200,200]],['minor','offroad'])]
    merged,count,added=merge_library(current,incoming,'routes',snap_to_roads=False,build_roads=False)
    assert count==1 and added==0 and merged['roads']==[] and current['route_library']==[]
    entry=merged['route_library'][0];assert entry['build_roads'] is False
    before=deepcopy(merged)
    for reverse in (False,True):
        route=follow_saved(merged['roads'],entry,POLICY,reverse=reverse)
        assert route.length==pytest.approx(200)
    assert merged==before
    with pytest.raises(RouteError):plan(merged['roads'],[[100,100],[200,200]],POLICY['allowed'])
    with pytest.raises(RouteError,match='未允许'):follow_saved(merged['roads'],entry,dict(allowed=['minor'],confirmed_only=False))
    with pytest.raises(RouteError,match='未实测'):follow_saved(merged['roads'],entry,dict(allowed=POLICY['allowed'],confirmed_only=True))
    with pytest.raises(RouteError,match='绕行道路'):follow_saved(merged['roads'],entry,POLICY,[dict(shape='rect',point=[100,150],width=20,height=20)])
    path=tmp_path/'仅收藏路线.json';atomic_json(path,library_payload(merged,'routes'))
    restored,_,added=merge_library(data(),read_project(path),'routes')
    assert restored['route_library']==merged['route_library'] and not restored['roads'] and added==0


def test_import_yes_builds_only_selected_routes_and_preserves_unrelated_private_routes():
    current=data();current['route_library']=[saved([[10,10],[20,10]],build_roads=False)]
    incoming=data();incoming['route_library']=[dict(saved([[200,100],[300,100]]),id='incoming')]
    merged,count,added=merge_library(current,incoming,'routes',build_roads=True)
    assert count==1 and added==1 and len(merged['roads'])==1
    assert merged['roads'][0]['points']==[[200,100],[300,100]]
    again,count,added=merge_library(merged,incoming,'routes',build_roads=True)
    assert again==merged and count==added==0


def test_snapped_import_is_atomic_and_export_preserves_guides_notes_and_options(tmp_path):
    current=data([road('road',[[100,100],[100,300],[300,300]])])
    incoming=data();incoming['route_library']=[saved([[110,110],[290,300]])]
    incoming['notes']=[dict(id='n',point=[100,300],type='square_left',grade=1,direction='both',text='左直角，别切',modifiers=['dont_cut'])]
    merged,count,added=merge_library(current,incoming,'routes',snap_to_roads=True)
    assert count==1 and added==0 and merged['roads']==current['roads']
    entry=merged['route_library'][0]
    assert len(entry['points'])>len(incoming['route_library'][0]['points'])
    path=tmp_path/'贴路收藏.json';atomic_json(path,library_payload(merged,'routes'))
    exported=read_project(path)
    assert exported['map']=='ozeti' and exported['meters_per_pixel']==5
    assert exported['route_library']==merged['route_library'] and exported['notes']==merged['notes']
    restored,_,_=merge_library(current,exported,'routes',snap_to_roads=False)
    assert restored['route_library']==merged['route_library'] and restored['roads']==current['roads']
    broken=deepcopy(incoming);broken['route_library'].append(dict(saved([[1000,1000],[1100,1100]]),id='unreachable'))
    before=deepcopy(current)
    with pytest.raises(RouteError):merge_library(current,broken,'routes',snap_to_roads=True)
    assert current==before


def test_dense_import_retains_reusable_controls_and_does_not_expand_on_reimport():
    roads=[road('line',[[100,100],[400,100]])]
    dense=saved([[100+i*.1,102] for i in range(2001)])
    first=snap_saved(roads,dense,POLICY)
    assert len(first['control_points'])==2
    second=snap_saved(roads,first,POLICY)
    assert first['control_points']==second['control_points'] and first['points']==second['points']


def test_new_route_metadata_is_validated_without_breaking_legacy_routes():
    p=data();p['route_library']=[saved([[10,10],[20,10]])]
    assert validate_project(p)==p
    for options in ({'build_roads':'false'},{'snap_to_roads':1},{'control_points':[[2000,2000],[0,0]]}):
        bad=deepcopy(p);bad['route_library'][0].update(options)
        with pytest.raises(ValueError):validate_project(bad)
