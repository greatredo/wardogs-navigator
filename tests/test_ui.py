import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import pytest
from PySide6.QtWidgets import QApplication,QDialog,QInputDialog,QFileDialog
from PySide6.QtCore import QTimer,Qt,QPointF
from PySide6.QtTest import QTest
from wardogs_nav.app import MainWindow,STYLE
from wardogs_nav.model import read_project,asset_path
from wardogs_nav.vision import Fix
from wardogs_nav.routing import blocked,distance


@pytest.fixture(scope='module')
def app():
    app=QApplication.instance() or QApplication([]);app.setStyleSheet(STYLE);return app


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path))
    w=MainWindow(start_worker=False)
    w.fix=Fix(x=505,y=1245,confidence=1,valid=True)
    w.project['destination']=[1300,796]
    w.show();app.processEvents();w.map.fit()
    yield w
    w.close();app.processEvents()


def test_drag_rectangle_replans_real_map(window,app):
    assert window.plan_route()
    old=list(window.route.points)
    window.set_tool('avoid')
    a=window.map.mapFromScene(QPointF(1143,780));b=window.map.mapFromScene(QPointF(1161,798))
    QTest.mousePress(window.map.viewport(),Qt.LeftButton,pos=a)
    QTest.mouseMove(window.map.viewport(),b,50)
    QTest.mouseRelease(window.map.viewport(),Qt.LeftButton,pos=b)
    app.processEvents()
    assert len(window.project['avoid'])==1 and window.project['avoid'][0]['shape']=='rect'
    assert window.route and old!=window.route.points
    assert all(not blocked(a,b,window.project['avoid'][0]) for a,b in zip(window.route.points,window.route.points[1:]))
    window.undo();assert not window.project['avoid']


def test_navigation_settings_and_soft_road_preferences_survive_restart(window,tmp_path):
    from PySide6.QtWidgets import QGroupBox
    from wardogs_nav.model import load_settings
    titles={g.title() for g in window.findChildren(QGroupBox)}
    assert {'常规导航设置','WRC 路书设置','通用驾驶提示'}<=titles
    window.navigation_fields['lead_m'].setValue(240)
    window.wrong_way_check.setChecked(False)
    loaded=load_settings()
    assert loaded['lead_m']==240 and 'normal_chain_count' not in loaded
    assert 'normal_bends' not in loaded and not loaded['wrong_way_alert']
    window.project['destination']=None;window.fix=None
    window.kind_preferences['offroad'].setCurrentIndex(window.kind_preferences['offroad'].findData('prefer'))
    window.kind_preferences['major'].setCurrentIndex(window.kind_preferences['major'].findData('avoid'))
    window.save_project()
    restored=MainWindow(start_worker=False)
    try:
        assert restored.kind_preferences['offroad'].currentData()=='prefer'
        assert restored.kind_preferences['major'].currentData()=='avoid'
        assert set(restored.project['policy']['allowed'])=={'major','minor','offroad'}
        assert restored.navigation_fields['lead_m'].value()==240
    finally:restored.close()


def test_bridge_editor_and_drag_keep_ground_crossing_separate(window,app,monkeypatch):
    from wardogs_nav.dialogs import RoadDialog
    from wardogs_nav.model import read_project
    from wardogs_nav.maps import project_path
    window.fix=None;window.project['destination']=None
    window.project['roads']=[dict(id=id,name=id,kind='major',points=points) for id,points in [
        ('deck',[[100,100],[200,100],[300,100]]),
        ('ground',[[200,50],[200,100],[200,150]]),
        ('approach',[[100,50],[100,100]])]]
    dialog=RoadDialog(window.project['roads'][0])
    assert not dialog.bridge.isChecked() and not dialog.bridge_start.isEnabled()
    dialog.bridge.setChecked(True)
    assert dialog.bridge_start.isEnabled() and not dialog.values()['bridge_start'] and not dialog.values()['bridge_end']
    dialog.close()
    def edit(dialog):
        dialog.bridge.setChecked(True);dialog.bridge_start.setChecked(True)
        return QDialog.Accepted
    monkeypatch.setattr(RoadDialog,'exec',edit)
    window.refresh_lists();window.road_list.setCurrentRow(0);window.edit_road();app.processEvents()
    assert window.project['roads'][0]['bridge'] and window.project['roads'][0]['bridge_start']
    assert '[桥梁]' in window.road_list.item(0).text()
    window.move_item(('road','deck',1),[220,110]);app.processEvents()
    assert window.project['roads'][0]['points'][1]==[220,110]
    assert window.project['roads'][1]['points'][1]==[200,100]
    window.move_item(('road','deck',0),[105,100]);app.processEvents()
    assert window.project['roads'][2]['points'][-1]==[105,100]
    window.save_project()
    assert read_project(project_path(window.project['map']))['roads'][0]['bridge']


def test_drag_destination_changes_config_and_route(window,app):
    assert window.plan_route()
    window.move_item(('destination',0),[194,211]);app.processEvents()
    assert window.project['destination']==[194,211] and window.route


def test_editing_danger_while_navigating_resumes(window,app):
    assert window.plan_route()
    window.fix_live=True;window.project['start']=[505,1245]
    window.navigator.start(window.route,[],window.settings,window.project['meters_per_pixel'],True)
    window.project['roundtrip']=True
    window.add_danger_region({'shape':'rect','point':[1152,789],'width':14,'height':14});app.processEvents()
    assert window.navigator.active and window.navigator.roundtrip
    assert window.project['start']==[505,1245]


def test_return_leg_targets_original_home_after_replan(window,app):
    assert window.plan_route()
    window.project['start']=[505,1245];window.project['roundtrip']=True
    window.navigator.start(window.route,[],window.settings,window.project['meters_per_pixel'],True)
    window.navigator.lap=1;window.navigator.leg='返程'
    window.fix=Fix(x=1300,y=796,valid=True)
    window.next_leg()
    assert window.navigator.active and distance(window.route.points[-1],window.project['start'])<1
    assert window.navigator.lap==1


def test_export_roundtrip_preserves_customization(window,tmp_path):
    from wardogs_nav.model import atomic_json
    window.project['avoid'].append({'shape':'rect','point':[1000,900],'width':70,'height':50})
    window.project['notes'].append(dict(id='user-note',point=[505,1245],type='right',grade=3,bearing=90,direction='both',lead_m=200,text='右三',reverse_text='左三'))
    path=tmp_path/'中文配置.json';atomic_json(path,window.project)
    loaded=read_project(path)
    assert loaded==window.project


def test_live_minimap_overlay_hides_and_clears_capture_mask_when_stale(window,app):
    import time
    from wardogs_nav.vision import read_image
    assert window.plan_route()
    window.worker.capture=True
    window.navigator.start(window.route,[],window.settings,window.project['meters_per_pixel'],False)
    window.on_fix(Fix(x=505,y=1245,scale=.35,valid=True),read_image(asset_path('sample_minimap.png')),True)
    app.processEvents()
    assert window.minimap_overlay.isVisible() and window.worker.path_mask
    window.fix_time=time.monotonic()-3;window.check_stale();app.processEvents()
    assert not window.minimap_overlay.isVisible() and window.worker.path_mask is None


@pytest.mark.parametrize('kind',['major','minor','offroad'])
def test_draw_road_using_map_and_property_dialog(window,app,kind):
    window.set_tool('road');window.draw_kind.setCurrentIndex(window.draw_kind.findData(kind));window.draw_snap.setChecked(False)
    count=len(window.project['roads'])
    for p in ([260,260],[290,290],[320,290]):
        QTest.mouseClick(window.map.viewport(),Qt.LeftButton,pos=window.map.mapFromScene(QPointF(*p)))
    assert len(window.map.draft)==3
    window.undo_draw_point();assert len(window.map.draft)==2
    def accept_road():
        dialog=app.activeModalWidget();dialog.name.setText('手绘测试道路');dialog.accept()
    QTimer.singleShot(0,accept_road);window.finish_road();app.processEvents()
    assert len(window.project['roads'])==count+1
    assert window.project['roads'][-1]['kind']==kind and window.project['roads'][-1]['confirmed']


def test_draw_favorite_export_import_and_load(window,app,tmp_path,monkeypatch):
    window.project['roads']=[];window.project['policy']['allowed']=['major','minor','offroad'];window.sync_policy()
    window.set_tool('favorite');window.draw_snap.setChecked(False)
    for p,kind in [([200,200],'major'),([300,200],'major'),([300,300],'offroad')]:
        window.draw_kind.setCurrentIndex(window.draw_kind.findData(kind))
        QTest.mouseClick(window.map.viewport(),Qt.LeftButton,pos=window.map.mapFromScene(QPointF(*p)))
    def accept_name():
        dialog=app.activeModalWidget();assert isinstance(dialog,QInputDialog)
        dialog.setTextValue('跨野地补给');dialog.accept()
    QTimer.singleShot(0,accept_name);window.finish_road();app.processEvents()
    saved=window.project['route_library'][0]
    assert saved['name']=='跨野地补给' and saved['kinds']==['major','offroad']
    assert len(window.project['roads'])==2 and all(r['confirmed'] for r in window.project['roads'])
    path=tmp_path/'路线收藏.json'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(path),''))
    window.export_library('routes');assert read_project(path)['route_library']==[saved]
    original_destination=window.project['destination']
    window.project['route_library']=[];window.project['roads']=[]
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(path),''))
    QTimer.singleShot(0,lambda:app.activeModalWidget().accept())
    window.import_library('routes')
    assert window.project['destination']==original_destination and len(window.project['roads'])==2
    window.favorite_list.setCurrentRow(0);window.load_favorite()
    assert window.route and distance(window.route.points[0],saved['points'][0])<1
    window.load_favorite(reverse=True)
    assert distance(window.route.points[0],saved['points'][-1])<1
    assert len(window.project['roads'])==2


def test_save_favorite_during_navigation_keeps_running(window,app):
    assert window.plan_route()
    window.navigator.start(window.route,[],window.settings,window.project['meters_per_pixel'])
    def accept_name():
        dialog=app.activeModalWidget();dialog.setTextValue('当前补给线');dialog.accept()
    QTimer.singleShot(0,accept_name);window.save_current_route()
    assert window.navigator.active and window.route
    assert window.project['route_library'][0]['points']==[list(p) for p in window.route.points]


def test_favorite_return_after_replan_uses_original_full_journey(window,app):
    from wardogs_nav.library import saved_route
    from wardogs_nav.routing import Route
    def road(id,points):return dict(id=id,name=id,kind='major',confirmed=True,points=points)
    window.project['roads']=[road('long',[[10,10],[10,110],[110,110],[110,10]]),road('short',[[10,10],[110,10]])]
    route=Route([[10,10],[10,110],[110,110],[110,10]],['major']*3,['long']*3,300,[0,0],0)
    saved=saved_route('环行补给',route);window.project['route_library']=[saved];window.project['active_route_id']=saved['id']
    window.project['destination']=[110,10];window.project['roundtrip']=True
    window.fix=Fix(x=10,y=10,valid=True);window.fix_live=True;window.begin_navigation()
    assert window.favorite_trip and window.route.length==pytest.approx(300)
    window.fix=Fix(x=10,y=80,valid=True);window.replan_navigation()
    assert window.route.length==pytest.approx(230)
    window.fix=Fix(x=110,y=10,valid=True);window.navigator.lap=1;window.navigator.leg='返程';window.next_leg()
    assert window.route.length==pytest.approx(300) and distance(window.route.points[-1],[10,10])<1
