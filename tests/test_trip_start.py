import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from copy import deepcopy
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog
from wardogs_nav.app import MainWindow,STYLE
from wardogs_nav.library import saved_route
from wardogs_nav.mapview import Handle
from wardogs_nav.model import validate_project,read_project
from wardogs_nav.maps import project_path
from wardogs_nav.routing import Route,distance,remaining_points
from wardogs_nav.vision import Fix,feature_mask


@pytest.fixture(scope='module')
def app():
    app=QApplication.instance() or QApplication([]);app.setStyleSheet(STYLE);return app


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path))
    w=MainWindow(start_worker=False);w.settings['voice']=False
    w.project['roads']=[dict(id='line',name='横路',kind='major',confirmed=True,
                            points=[[100,100],[200,100],[400,100],[600,100],[800,100]]),
                        dict(id='branch',name='支路',kind='major',confirmed=True,
                            points=[[100,100],[100,300]])]
    w.project['destination']=[600,100];w.project['roundtrip']=True;w.project['meters_per_pixel']=1
    w.fix=Fix(x=100,y=100,scale=1,confidence=1,valid=True);w.fix_live=True;w.fix_time=time.monotonic()
    w.frame=np.full((300,400,3),80,np.uint8);w.worker.capture=True
    w.sync_policy();w.refresh_lists();w.refresh_map();w.show();app.processEvents()
    yield w
    w.close();app.processEvents()


def test_start_button_waits_for_valid_fix_then_places_start_once(window,monkeypatch):
    monkeypatch.setattr(window.worker,'isRunning',lambda:True)
    window.fix=None;window.fix_live=False;window.start_navigation()
    assert window.pending_start and window.project['start'] is None
    window.on_fix(Fix(valid=False),window.frame,True)
    assert window.project['start'] is None and not window.navigator.active
    window.on_fix(Fix(x=100,y=100,scale=1,confidence=1,valid=True),window.frame,True)
    assert window.navigator.active and window.project['start']==[100,100]
    window.stop_navigation(quiet=True);window.fix=Fix(x=400,y=100,valid=True)
    window.begin_navigation()
    assert window.project['start']==[100,100] and window.route.points[0]==(400,100)
    assert window.full_route.points[0]==(100,100)
    assert '100, 100' in window.start_label.text()


def test_map_set_drag_and_current_position_controls(window,app):
    window.tabs.widget(0).ensureWidgetVisible(window.set_start_button)
    QTest.mouseClick(window.set_start_button,Qt.LeftButton)
    pos=window.map.mapFromScene(QPointF(100,300))
    QTest.mouseClick(window.map.viewport(),Qt.LeftButton,pos=pos);app.processEvents()
    assert distance(window.project['start'],[100,300])<3
    assert any(isinstance(item,Handle) and item.key==('start',0) for item in window.map.scene().items())
    window.move_item(('start',0),[200,100]);app.processEvents()
    assert window.project['start']==[200,100]
    window.undo();assert distance(window.project['start'],[100,300])<3
    window.tabs.widget(0).ensureWidgetVisible(window.current_start_button)
    QTest.mouseClick(window.current_start_button,Qt.LeftButton)
    assert window.project['start']==[100,100]
    window.fix_time=time.monotonic()-3;window.fix.x=400
    window.use_current_start();assert window.project['start']==[100,100]


def test_change_destination_mid_outbound_keeps_origin_and_remaining_waypoints(window,app):
    window.project['waypoints']=[[200,100]];window.begin_navigation()
    window.navigator.progress=300;window.fix=Fix(x=400,y=100,valid=True)
    window.set_tool('destination');window.map_click(800,100)
    assert window.navigator.active and window.navigator.lap==0
    assert window.project['start']==[100,100] and window.project['destination']==[800,100]
    assert window.route.points[0]==(400,100) and window.route.length==pytest.approx(400)
    assert window.full_route.points[0]==(100,100) and window.full_route.length==pytest.approx(700)
    assert '返程终点' in window.start_label.text()
    window.fix=Fix(x=800,y=100,valid=True);window.navigator.lap=1;window.navigator.leg='返程';window.next_leg()
    assert window.route.points[-1]==(100,100) and window.navigator.active


@pytest.mark.parametrize('returning',[False,True])
def test_edit_start_updates_return_endpoint_from_current_position(window,app,returning):
    window.begin_navigation()
    if returning:
        window.fix=Fix(x=600,y=100,valid=True);window.navigator.lap=1;window.navigator.leg='返程';window.next_leg()
    window.fix=Fix(x=400,y=100,valid=True)
    window.navigator.progress=200 if returning else 300
    window.move_item(('start',0),[100,300]);app.processEvents()
    assert window.navigator.active and window.navigator.lap==int(returning)
    assert window.route.points[0]==(400,100)
    assert window.route.points[-1]==((100,300) if returning else (600,100))
    assert window.full_route.points[0]==((600,100) if returning else (100,300))
    if not returning:
        window.fix=Fix(x=600,y=100,valid=True);window.navigator.lap=1;window.navigator.leg='返程';window.next_leg()
    assert window.route.points[-1]==(100,300) and window.project['destination']==[600,100]


def test_change_destination_on_return_preserves_current_return_target(window):
    window.begin_navigation();window.fix=Fix(x=600,y=100,valid=True)
    window.navigator.lap=1;window.navigator.leg='返程';window.next_leg()
    window.fix=Fix(x=400,y=100,valid=True);window.navigator.progress=200
    window.set_tool('destination');window.map_click(800,100)
    assert window.navigator.active and window.navigator.lap==1
    assert window.route.points[0]==(400,100) and window.route.points[-1]==(100,100)
    assert window.full_route.points[0]==(800,100)
    window.fix=Fix(x=100,y=100,valid=True);window.navigator.lap=2;window.navigator.leg='去程';window.next_leg()
    assert window.route.points[-1]==(800,100)


def test_start_persistence_preview_without_fix_and_map_isolation(window,app,tmp_path,monkeypatch):
    window.fix=None;window.fix_live=False;window.set_start([100,300])
    assert window.route.points[0]==(100,300) and window.route.points[-1]==(600,100)
    path=tmp_path/'起始点配置.json'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(path),''))
    window.export_project();assert read_project(path)['start']==[100,300]
    window.set_start([200,100])
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(path),''))
    window.import_project();assert window.project['start']==[100,300]
    assert window.switch_map('bakurani') and window.project['start'] is None
    window.set_start([500,500]);window.clear_current_route()
    assert window.switch_map('ozeti') and window.project['start']==[100,300]
    window.close();app.processEvents()
    reopened=MainWindow(start_worker=False)
    try:
        assert reopened.project['start']==[100,300]
        assert reopened.plan_route() and reopened.route.points[0]==(100,300)
        reopened.clear_current_route();reopened.save_project()
        assert read_project(project_path('ozeti'))['start'] is None
    finally:reopened.close()


def test_old_config_and_invalid_start_validation(window):
    legacy=deepcopy(window.project);legacy.pop('start')
    assert validate_project(legacy)['start'] is None and 'start' not in legacy
    for invalid in ([True,100],[float('nan'),100],[-1,100],[100],{'x':100,'y':100}):
        legacy['start']=invalid
        with pytest.raises(ValueError):validate_project(legacy)


def test_private_favorite_keeps_full_path_when_start_changes(window,app):
    window.project['roads']=[]
    full=Route([[100,100],[100,300],[600,300],[600,100]],['major']*3,['private']*3,900,[0,0],0)
    saved=saved_route('独立收藏',full,build_roads=False)
    window.project['route_library']=[saved];window.project['active_route_id']=saved['id']
    window.begin_navigation()
    window.fix=Fix(x=300,y=300,valid=True);window.navigator.progress=400
    window.move_item(('start',0),[100,200]);app.processEvents()
    assert window.navigator.active and not window.project['roads']
    assert window.full_route.points[0]==(100,200) and window.route.points[0]==(300,300)
    window.fix=Fix(x=600,y=100,valid=True);window.navigator.lap=1;window.navigator.leg='返程';window.next_leg()
    assert window.route.points[-1]==(100,200) and window.route.length==pytest.approx(800)
    assert window.project['route_library']==[saved] and not window.project['roads']


def test_overlay_shrinks_at_segment_progress_and_resets_on_return(window):
    window.begin_navigation()
    window.navigator.update((250,100),now=1)
    window.fix=Fix(x=250,y=100,scale=1,valid=True);window.update_minimap_overlay()
    overlay=window.minimap_overlay
    assert overlay.full_points[0]==pytest.approx((50,150))
    assert overlay.points[0]==pytest.approx((200,150))
    before=overlay.grab().toImage()
    assert 0<before.pixelColor(100,150).alpha()<before.pixelColor(300,150).alpha()
    window.navigator.update((330,100),now=3)
    assert remaining_points(window.route,window.navigator.progress)[0]==pytest.approx((330,100))
    assert window.full_route.points[0]==(100,100)
    window.fix=Fix(x=600,y=100,scale=1,valid=True)
    window.navigator.lap=1;window.navigator.leg='返程';window.next_leg();window.update_minimap_overlay()
    assert window.navigator.progress==0 and overlay.points[0]==pytest.approx((200,150))
    assert window.full_route.points[0]==(600,100) and window.route.points[-1]==(100,100)
    window.navigator.update((450,100),now=5)
    assert remaining_points(window.route,window.navigator.progress)[0]==pytest.approx((450,100))
    assert remaining_points(window.route,window.route.length)==[]
    window.clear_current_route()
    assert not overlay.points and not overlay.full_points and window.worker.path_mask is None


def test_stopped_reverse_favorite_preview_keeps_endpoint_direction(window):
    window.project['roads']=[]
    full=Route([[100,100],[100,300],[600,300],[600,100]],['major']*3,['private']*3,900,[0,0],0)
    saved=saved_route('反向收藏',full,build_roads=False)
    window.project['route_library']=[saved];window.refresh_lists();window.favorite_list.setCurrentRow(0)
    window.load_favorite(reverse=True);window.fix=Fix(x=600,y=100,valid=True);window.begin_navigation()
    window.stop_navigation(quiet=True);window.changed()
    assert window.route and not window.navigator.active
    assert window.full_route.points[0]==pytest.approx((600,100)) and window.full_route.points[-1]==pytest.approx((100,100))
    assert window.project['start']==[600,100] and window.project['destination']==[100,100]
    assert window.project['route_library']==[saved] and not window.project['roads']


def test_capture_mask_covers_full_and_remaining_paths_without_connecting_them():
    image=np.full((300,400,3),80,np.uint8)
    mask=feature_mask(image,path_mask={'paths':[[(50,80),(350,80)],[(50,220),(350,220)]],'width':4})
    assert mask[80,120]==0 and mask[220,120]==0
    assert mask[150,120]==255  # No diagonal connector between separate lines.
    legacy=feature_mask(image,path_mask=([(50,80),(350,80)],4))
    assert legacy[80,120]==0 and legacy[220,120]==255
