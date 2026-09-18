import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import pytest
from PySide6.QtWidgets import QApplication,QDialogButtonBox,QFileDialog
from PySide6.QtCore import QTimer,Qt,QPointF,QPoint
from PySide6.QtTest import QTest
from wardogs_nav.app import MainWindow
from wardogs_nav.dialogs import FavoriteImportDialog,RoadDialog
from wardogs_nav.model import atomic_json,read_project
from wardogs_nav.library import library_payload
from wardogs_nav.vision import Fix


def road(id,points,kind='minor'):
    return dict(id=id,name=id,points=points,kind=kind,confirmed=True)


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path))
    w=MainWindow(start_worker=False);w.show();app.processEvents();w.map.fit()
    yield w
    w.close();app.processEvents()


def click(window,x,y,button=Qt.LeftButton):
    QTest.mouseClick(window.map.viewport(),button,pos=window.map.mapFromScene(QPointF(x,y)))


def test_select_double_click_edit_and_context_delete_road_without_list_search(window,app):
    window.project['roads']=[road('west',[[200,200],[500,200]]),road('east',[[200,300],[500,300]])]
    window.refresh_lists();window.refresh_map();window.set_tool('pan')
    click(window,340,300)
    assert window.map.selected_road=='east' and window.road_list.currentRow()==1
    def edit():
        dialog=app.activeModalWidget();assert isinstance(dialog,RoadDialog)
        dialog.name.setText('地图双击修改');dialog.kind.setCurrentIndex(dialog.kind.findData('major'));dialog.accept()
    QTimer.singleShot(0,edit)
    QTest.mouseDClick(window.map.viewport(),Qt.LeftButton,pos=window.map.mapFromScene(QPointF(350,300)))
    assert window.project['roads'][1]['name']=='地图双击修改' and window.project['roads'][1]['kind']=='major'
    window.undo();assert window.project['roads'][1]['name']=='east'
    def remove():
        menu=app.activePopupWidget()
        next(a for a in menu.actions() if a.text()=='删除整条道路').trigger();menu.close()
    QTimer.singleShot(0,remove);click(window,350,300,Qt.RightButton)
    assert [r['id'] for r in window.project['roads']]==['west']
    window.undo();assert len(window.project['roads'])==2


def test_road_hit_testing_uses_zoom_independent_tolerance_and_does_not_take_drawing_clicks(window):
    window.project['roads']=[road('line',[[200,200],[500,200]])];window.refresh_map()
    for scale in (.6,1.8):
        window.map.resetTransform();window.map.scale(scale,scale)
        location=window.map.mapFromScene(QPointF(350,200))
        assert window.map.road_at(location+QPoint(0,6))=='line'
        assert window.map.road_at(location+QPoint(0,15)) is None
    window.map.fit();window.set_tool('destination');click(window,350,200)
    assert window.project['destination']==pytest.approx([350,200],abs=5)
    window.set_tool('pan');click(window,100,100)
    assert window.map.selected_road is None


def test_coarse_favorite_draw_has_live_road_preview_and_saves_full_path(window,app):
    window.project['roads']=[road('bend',[[150,150],[150,450],[450,450]])]
    original=deepcopy(window.project['roads']);window.set_tool('favorite');window.favorite_snap.setChecked(True)
    click(window,160,160);click(window,440,440)
    assert window.draft_preview and len(window.map.draft_path)>2
    assert not window.draw_kind.isEnabled()
    assert not window.favorite_build.isVisible() and not window.draw_snap.isVisible()
    QTimer.singleShot(0,lambda:(app.activeModalWidget().setTextValue('粗绘贴路'),app.activeModalWidget().accept()))
    window.finish_favorite()
    saved=window.project['route_library'][0]
    assert saved['snap_to_roads'] and not saved['build_roads']
    assert len(saved['control_points'])==2 and [150,450] in saved['points']
    assert window.project['roads']==original
    window.favorite_list.setCurrentRow(0);window.load_favorite()
    assert window.route.length>560 and window.project['roads']==original


def test_unreachable_drawing_keeps_draft_and_does_not_create_straight_road(window):
    window.project['roads']=[road('left',[[150,150],[200,150]]),road('right',[[500,150],[600,150]])]
    original=deepcopy(window.project['roads']);window.set_tool('favorite');window.favorite_snap.setChecked(True)
    click(window,160,160);click(window,590,160)
    assert window.draft_preview is None
    window.finish_favorite()
    assert len(window.map.draft)==2 and not window.project['route_library'] and window.project['roads']==original
    assert '无法贴合' in window.banner.text()


@pytest.mark.parametrize('choice',['cancel','private','public','snap'])
def test_import_options_are_real_user_choices(window,app,tmp_path,monkeypatch,choice):
    window.project['roads']=[road('bend',[[150,150],[150,450],[450,450]])]
    incoming=deepcopy(window.project);incoming['roads']=[]
    incoming['route_library']=[dict(id='route',name='导入走法',points=[[160,160],[440,440]],kinds=['minor'])]
    path=tmp_path/'待导入.json';atomic_json(path,incoming)
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(path),''))
    before=deepcopy(window.project)
    def choose():
        dialog=app.activeModalWidget();assert isinstance(dialog,FavoriteImportDialog)
        assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
        if choice=='cancel':dialog.reject();return
        if choice=='snap':dialog.snap.setChecked(True)
        else:dialog.road_action.setCurrentIndex(1 if choice=='public' else 2)
        assert dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
        dialog.accept()
    QTimer.singleShot(0,choose);window.import_library('routes')
    if choice=='cancel':assert window.project==before;return
    saved=window.project['route_library'][0]
    assert saved['build_roads']==(choice=='public')
    assert saved['snap_to_roads']==(choice=='snap')
    if choice=='public':assert len(window.project['roads'])>len(before['roads'])
    else:assert window.project['roads']==before['roads']
    if choice=='snap':assert [150,450] in saved['points']
    else:assert saved['points']==incoming['route_library'][0]['points']


def test_private_route_stays_private_through_replan_return_restart_and_export(window,app,tmp_path):
    window.project['roads']=[];window.project['policy']['allowed']=['minor','offroad']
    saved=dict(id='private',name='仅收藏',points=[[100,100],[100,300],[300,300]],kinds=['minor','offroad'],snap_to_roads=False,build_roads=False)
    window.store_favorite(saved);window.favorite_list.setCurrentRow(0);window.load_favorite()
    assert window.route.length==pytest.approx(400) and window.project['roads']==[]
    window.fix=Fix(x=100,y=100,valid=True);window.fix_live=True;window.project['roundtrip']=True;window.begin_navigation()
    assert window.favorite_trip['build_roads'] is False
    window.fix=Fix(x=100,y=200,valid=True);window.replan_navigation()
    assert window.route.length==pytest.approx(300)
    window.fix=Fix(x=300,y=300,valid=True);window.navigator.lap=1;window.navigator.leg='返程';window.next_leg()
    assert window.route.length==pytest.approx(400) and window.route.points[-1]==pytest.approx([100,100])
    assert window.project['roads']==[]
    window.save_project();path=tmp_path/'完整收藏.json';atomic_json(path,library_payload(window.project,'routes'))
    assert read_project(path)['route_library']==[saved]
    restored=MainWindow(start_worker=False)
    try:
        assert restored.project['route_library']==[saved] and restored.project['roads']==[]
        restored.favorite_list.setCurrentRow(0);restored.load_favorite(reverse=True)
        assert restored.route.length==pytest.approx(400) and restored.project['roads']==[]
    finally:restored.close();app.processEvents()
