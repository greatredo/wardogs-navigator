import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton
from wardogs_nav.app import MainWindow
from wardogs_nav.model import read_project,validate_project,atomic_json
from wardogs_nav.maps import map_asset,project_path
from wardogs_nav.routing import plan
from wardogs_nav.vision import Fix


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
    window.fix_live=True;window.home=[505,1245]
    window.project['destination']=[1300,796];window.project['roundtrip']=True
    window.project['avoid']=[dict(shape='rect',point=[1152,789],width=14,height=14)]
    window.refresh_lists();assert window.plan_route()
    window.navigator.start(window.route,[],window.settings,window.project['meters_per_pixel'],True)
    window.clear_annotations('avoid')
    assert window.project['avoid']==[] and window.navigator.active
    assert window.navigator.roundtrip and window.home==[505,1245]
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
