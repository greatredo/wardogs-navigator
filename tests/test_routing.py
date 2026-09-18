from copy import deepcopy
import pytest
from wardogs_nav.routing import plan, RouteError, blocked, distance
from wardogs_nav.model import read_project,asset_path,validate_project


def road(id,points,kind='major',confirmed=True):
    return dict(id=id,name=id,points=points,kind=kind,confirmed=confirmed)


@pytest.fixture
def roads():
    return [road('direct',[[0,0],[50,0],[100,0]]),road('detour',[[0,0],[0,50],[100,50],[100,0]],'minor'),road('field',[[0,0],[50,25],[100,0]],'offroad',False)]


def test_road_filters_are_hard_constraints(roads):
    direct=plan(roads,[[0,0],[100,0]],['major']);assert direct.length==100
    minor=plan(roads,[[0,0],[100,0]],['minor']);assert minor.length==200
    field=plan(roads,[[0,0],[100,0]],['offroad']);assert set(field.kinds)=={'offroad'}
    with pytest.raises(RouteError):plan(roads,[[0,0],[100,0]],['offroad'],True)


@pytest.mark.parametrize('zone',[{'point':[50,0],'radius':10},{'shape':'rect','point':[50,0],'width':20,'height':20}])
def test_danger_regions_force_detour(roads,zone):
    route=plan(roads,[[0,0],[100,0]],['major','minor'],avoid=[zone]);assert route.length==200
    assert all(not blocked(a,b,zone) for a,b in zip(route.points,route.points[1:]))
    with pytest.raises(RouteError):plan(roads,[[0,0],[100,0]],['major'],avoid=[zone])


def test_target_inside_danger_is_rejected(roads):
    with pytest.raises(RouteError,match='危险区域内'):plan(roads,[[0,0],[50,0]],['major'],avoid=[{'shape':'rect','point':[50,0],'width':20,'height':20}])


def test_waypoints_are_visited_in_order(roads):
    route=plan(roads,[[0,0],[25,50],[80,50],[100,0]],['major','minor'])
    assert route.points.index((25.,50.))<route.points.index((80.,50.))


def test_no_invented_links_across_gap():
    roads=[road('a',[[0,0],[40,0]]),road('b',[[60,0],[100,0]])]
    with pytest.raises(RouteError,match='不连通'):plan(roads,[[0,0],[100,0]],['major'])


def test_crossing_without_vertex_does_not_imply_junction():
    roads=[road('a',[[0,50],[100,50]]),road('b',[[50,0],[50,100]])]
    with pytest.raises(RouteError):plan(roads,[[0,50],[50,100]],['major'])
    roads[1]['points']=[[50,0],[50,50],[50,100]]
    route=plan(roads,[[0,50],[50,100]],['major']);assert route.length==100


def test_far_target_is_not_silently_connected(roads):
    with pytest.raises(RouteError,match='过远'):plan(roads,[[0,0],[300,300]],['major'])


def test_sample_map_connects_bases_and_supports_danger_detour():
    p=read_project(asset_path('default_project.json'))
    route=plan(p['roads'],[[505,1245],[1300,796]],['major','minor'])
    assert route.length>1000
    assert max(route.snap_distances)<5
    zone={'shape':'rect','point':[1152,789],'width':14,'height':14}
    detour=plan(p['roads'],[[505,1245],[1300,796]],['major','minor'],avoid=[zone])
    assert detour.points!=route.points
    assert all(not blocked(a,b,zone) for a,b in zip(detour.points,detour.points[1:]))


def test_config_rejects_bad_coordinates_and_duplicates():
    p=read_project(asset_path('default_project.json'))
    assert validate_project(p)['roads']==p['roads']
    invalid=deepcopy(p);invalid['roads'][0]['points'][0][0]=float('nan')
    with pytest.raises(ValueError):validate_project(invalid)
    invalid=deepcopy(p);invalid['roads'].append(invalid['roads'][0])
    with pytest.raises(ValueError):validate_project(invalid)
    invalid=deepcopy(p);invalid['map']='other'
    with pytest.raises(ValueError):validate_project(invalid)


def test_rectangle_validation_and_tangent_intersection():
    p=read_project(asset_path('default_project.json'));p['avoid']=[{'shape':'rect','point':[500,500],'width':40,'height':20}]
    validate_project(p)
    zone=p['avoid'][0]
    assert blocked([480,490],[520,490],zone)
    assert not blocked([479,470],[479,530],zone)


@pytest.mark.parametrize('key,value',[('roads',[1]),('notes',['bad']),('avoid',[False]),('destinations',[None]),('policy',[])])
def test_invalid_import_structures_raise_readable_errors(key,value):
    p=read_project(asset_path('default_project.json'));p[key]=value
    with pytest.raises(ValueError):validate_project(p)
