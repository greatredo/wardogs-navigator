import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from copy import deepcopy
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton
from wardogs_nav.app import MainWindow
from wardogs_nav.model import read_project,validate_project,atomic_json,asset_path
from wardogs_nav.library import saved_route
from wardogs_nav.maps import map_asset,project_path
from wardogs_nav.routing import plan
from wardogs_nav.vision import Fix,read_image


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path))
    w=MainWindow(start_worker=False);w.show();app.processEvents()
    yield w
    w.close();app.processEvents()


@pytest.mark.parametrize('map_id',['ozeti','bakurani','zestafona'])
def test_legacy_road_confirmation_migrates_without_losing_geometry(map_id,tmp_path):
    old=read_project(map_asset(map_id,'project'))
    old['roads'][0]['confirmed']=False
    old['roads'][1].pop('confirmed')
    old['policy']['confirmed_only']=True
    before=deepcopy(old)
    current=validate_project(old)
    assert old==before
    assert current['roads'][0]['points']==before['roads'][0]['points']
    assert all(r['confirmed'] for r in current['roads'])
    assert current['policy']['confirmed_only'] is False
    path=tmp_path/'共享配置.json';atomic_json(path,current)
    assert read_project(path)==current
    road=dict(id='legacy',kind='major',confirmed=False,points=[[100,100],[200,100]])
    assert plan([road],[[100,100],[200,100]],['major'],confirmed_only=True).length==100


@pytest.mark.parametrize('key',['waypoints','avoid'])
@pytest.mark.parametrize('location',['navigation','toolbar'])
def test_clear_buttons_preserve_other_data_and_can_undo(window,app,key,location):
    window.project['waypoints']=[[505,1245],[1200,700]]
    window.project['avoid']=[dict(shape='rect',point=[500,500],width=20,height=20)]
    window.project['destination']=[1300,796]
    window.changed(replan=False)
    before=deepcopy(window.project)
    button=window.findChild(QPushButton,'clear_'+key+'_'+location)
    assert button and button.isEnabled()
    if location=='navigation':window.tabs.widget(0).ensureWidgetVisible(button)
    QTest.mouseClick(button,Qt.LeftButton);app.processEvents()
    expected=deepcopy(before);expected[key]=[]
    assert window.project==expected
    for place in ('navigation','toolbar'):
        assert not window.findChild(QPushButton,'clear_'+key+'_'+place).isEnabled()
    history=len(window.history);window.clear_annotations(key)
    assert len(window.history)==history
    window.save_project();assert read_project(project_path('ozeti'))[key]==[]
    window.undo();app.processEvents()
    assert window.project==before and button.isEnabled()


def test_clear_danger_replans_running_navigation_and_preserves_roundtrip(window,app):
    window.fix=Fix(x=505,y=1245,confidence=1,valid=True)
    window.fix_live=True;window.project['start']=[505,1245]
    window.project['destination']=[1300,796];window.project['roundtrip']=True
    window.project['avoid']=[dict(shape='rect',point=[1152,789],width=14,height=14)]
    window.refresh_lists();assert window.plan_route()
    window.navigator.start(window.route,[],window.settings,window.project['meters_per_pixel'],True)
    window.clear_annotations('avoid')
    assert window.project['avoid']==[] and window.navigator.active
    assert window.navigator.roundtrip and window.project['start']==[505,1245]
    assert window.project['destination']==[1300,796]


def test_clear_is_saved_per_map(window):
    window.project['waypoints']=[[500,500]];window.project['avoid']=[]
    assert window.switch_map('bakurani')
    window.project['waypoints']=[[900,900]]
    window.clear_annotations('waypoints')
    assert window.switch_map('ozeti')
    assert window.project['waypoints']==[[500,500]]
    assert window.switch_map('bakurani')
    assert window.project['waypoints']==[]


@pytest.mark.parametrize('location',['navigation','toolbar'])
@pytest.mark.parametrize('state',['navigating','stopped','waiting','hidden'])
def test_clear_current_route_ends_trip_without_losing_saved_data(window,app,monkeypatch,location,state):
    window.fix=Fix(x=505,y=1245,scale=.4,confidence=1,valid=True)
    window.fix_live=True;window.fix_time=time.monotonic();window.worker.capture=True
    window.frame=read_image(asset_path('sample_minimap.png'))
    window.project['destination']=[1300,796];assert window.plan_route(quiet=True)
    saved=saved_route('保留的路线收藏',window.route,build_roads=False)
    window.project['route_library']=[saved];window.project['active_route_id']=saved['id']
    window.project['active_route_reverse']=False;window.favorite_trip=saved
    window.project['waypoints']=[list(window.route.points[len(window.route.points)//2])]
    window.project['destinations']=[dict(name='保留的目的地',point=[1300,796])]
    window.project['avoid']=[dict(shape='rect',point=[450,700],width=30,height=30)]
    window.project['roundtrip']=True;window.project['start']=[505,1245]
    window.navigator.start(window.route,[],window.settings,window.project['meters_per_pixel'],True)
    window.navigator.lap=1;window.navigator.leg='返程'
    window.hud.show();window.update_minimap_overlay();window.refresh_lists();app.processEvents()
    assert window.minimap_overlay.isVisible() and window.worker.path_mask
    if state!='navigating':
        window.stop_navigation(quiet=True)
        assert window.route and window.map.route  # The reported stopped preview.
    if state=='waiting':window.pending_start=True
    if state=='hidden':window.hud.hide()
    before=deepcopy(window.project);stops=[];spoken=[]
    monkeypatch.setattr(window.tts,'stop',lambda:stops.append(True))
    monkeypatch.setattr(window,'speak',spoken.append)
    button=window.findChild(QPushButton,'clear_current_route_'+location)
    if location=='navigation':window.tabs.widget(0).ensureWidgetVisible(button)
    QTest.mouseClick(button,Qt.LeftButton);app.processEvents()
    expected=deepcopy(before);expected['start']=None;expected['destination']=None;expected['waypoints']=[]
    expected.pop('active_route_id');expected.pop('active_route_reverse')
    assert window.project==expected and stops
    assert not window.navigator.active and not window.pending_start
    assert window.route is None and window.map.route is None
    assert window.project['start'] is None and window.favorite_trip is None
    assert window.hud.isVisible()==(state!='hidden') and 'cue' not in window.hud.data
    assert not window.minimap_overlay.isVisible() and not window.minimap_overlay.points
    assert window.worker.path_mask is None
    assert '清除' in window.route_label.text() and '选择' in window.route_label.text()
    # An already queued camera result must not restart the cleared journey.
    window.on_fix(Fix(x=505,y=1245,scale=.4,confidence=1,valid=True),window.frame,True)
    assert not window.navigator.active and window.route is None and not spoken
    assert not window.minimap_overlay.isVisible() and window.hud.isVisible()==(state!='hidden')
    QTest.qWait(650)
    restored=read_project(project_path('ozeti'))
    assert restored['start'] is None and restored['destination'] is None and restored['waypoints']==[]
    assert not restored.get('active_route_id') and restored['route_library']==[saved]
    window.undo();app.processEvents()
    assert window.project==before and window.route is not None
    assert not window.navigator.active and not window.pending_start


def test_clear_current_route_persists_across_restart_and_leaves_other_map(window,app):
    window.project['destination']=[1300,796];window.project['waypoints']=[[505,1245]]
    assert window.switch_map('bakurani')
    window.project['destination']=[900,900];window.project['waypoints']=[[800,800]]
    window.clear_current_route();window.close();app.processEvents()
    reopened=MainWindow(start_worker=False)
    try:
        assert reopened.project['map']=='bakurani'
        assert reopened.project['destination'] is None and reopened.project['waypoints']==[]
        assert reopened.route is None and not reopened.pending_start
        assert reopened.switch_map('ozeti')
        assert reopened.project['destination']==[1300,796] and reopened.project['waypoints']==[[505,1245]]
    finally:reopened.close()


def test_clearing_empty_route_does_not_add_undo_steps_and_new_trip_can_start(window):
    window.clear_current_route();history=len(window.history)
    window.clear_current_route();assert len(window.history)==history
    window.fix=Fix(x=505,y=1245,scale=.4,confidence=1,valid=True)
    window.project['destination']=[194,211];window.begin_navigation()
    assert window.navigator.active and window.route
    assert window.project['start']==[505,1245] and window.navigator.lap==0
