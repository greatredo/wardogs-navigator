from copy import deepcopy
from wardogs_nav.model import asset_path,read_project,upgrade_road_data


def test_map_upgrade_preserves_user_destinations_zones_and_roads():
    old=read_project(asset_path('legacy-road-seed.json'))
    old['avoid']=[{'shape':'rect','point':[500,500],'width':40,'height':20}]
    old['destination']=[1200,700]
    road=dict(deepcopy(old['roads'][0]),id='user-road',name='用户自定义道路')
    old['roads'].append(road)
    updated,changed=upgrade_road_data(old)
    assert changed and updated['road_data_revision']==2
    assert updated['avoid']==old['avoid'] and updated['destination']==old['destination']
    assert road in updated['roads'] and old['roads'][0] not in updated['roads']
    assert len(old['roads'])==34


def test_user_road_edits_or_deletions_are_not_silently_replaced():
    old=read_project(asset_path('legacy-road-seed.json'));old['roads'][0]['name']='用户修改过的道路名称'
    updated,changed=upgrade_road_data(old)
    assert not changed and updated==old
    old['roads'].pop()
    assert not upgrade_road_data(old)[1]
