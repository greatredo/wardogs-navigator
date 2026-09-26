import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from copy import deepcopy
import pytest
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout,QInputDialog,QAbstractSpinBox,QComboBox,QScrollArea
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from wardogs_nav.app import MainWindow
from wardogs_nav.vision import Fix
from wardogs_nav.dialogs import number,RoadDialog


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path))
    w=MainWindow(start_worker=False);w.show();app.processEvents()
    yield w
    w.close();app.processEvents()


def wheel(widget,delta=-120):
    pos=widget.rect().center()
    event=QWheelEvent(QPointF(pos),QPointF(widget.mapToGlobal(pos)),QPoint(0,0),QPoint(0,delta),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    QApplication.sendEvent(widget,event)


def test_wheel_never_edits_focused_settings_but_scrolls_page_and_map(window,app):
    spin=window.navigation_fields['lead_m'];before=spin.value();spin.setFocus();wheel(spin)
    wheel(spin.lineEdit());assert spin.value()==before
    combo=window.mode;old=combo.currentIndex();combo.setFocus();wheel(combo)
    assert combo.currentIndex()==old
    dialog=RoadDialog(dict(kind='major',points=[[10,10],[20,20]]),window)
    old=dialog.kind.currentIndex();wheel(dialog.kind);assert dialog.kind.currentIndex()==old
    inp=QInputDialog(window);inp.setInputMode(QInputDialog.IntInput);inp.setIntValue(30)
    control=inp.findChild(QAbstractSpinBox);wheel(control);assert inp.intValue()==30
    # A long settings page still scrolls when the pointer is over a numeric field.
    page=QDialog(window);layout=QVBoxLayout(page);scroll=QScrollArea();layout.addWidget(scroll)
    content=QDialog();fields=QVBoxLayout(content)
    for _ in range(30):fields.addWidget(number(20,0,100))
    scroll.setWidget(content);page.resize(280,220);page.show();app.processEvents()
    control=content.findChild(QAbstractSpinBox);wheel(control)
    assert scroll.verticalScrollBar().value()>0 and control.value()==20
    transform=window.map.transform().m11();wheel(window.map.viewport(),120)
    assert window.map.transform().m11()>transform
    page.close();inp.close();dialog.close()


def test_manual_live_only_loss_break_persistence_and_undo(window,app,tmp_path,monkeypatch):
    import wardogs_nav.app as module
    times=iter([0,1,2,3,4,5,6,7]);monkeypatch.setattr(module.time,'monotonic',lambda:next(times,7))
    window.project['roads']=[];window.recorder.set_roads([]);window.worker.capture=True
    window.start_recording()
    window.on_fix(Fix(x=10,y=100,valid=True),None,False)
    assert window.recorder.state['manual']==[]
    for x in (10,15,20):window.on_fix(Fix(x=x,y=100,valid=True),None,True)
    window.invalidate_fix('定位丢失')
    assert '等待有效定位' in window.record_status.text()
    for x in (40,45,50):window.on_fix(Fix(x=x,y=100,valid=True),None,True)
    window.save_recording()
    data=json.loads((tmp_path/'recordings/ozeti.json').read_text(encoding='utf-8'))
    assert len(data['state']['manual'])==2
    window.finish_recording();assert len(window.project['roads'])==2
    window.undo();assert window.project['roads']==[]


def test_auto_recording_settings_and_counts_survive_map_switch(window):
    window.auto_record.setChecked(True);window.record_minimum.setValue(4)
    for i,x in enumerate(range(10,51,2)):window.recorder.feed([x,10],i*.7,True)
    window.disconnect_recording();before=deepcopy(window.recorder.state)
    assert before['units']
    assert window.switch_map('bakurani')
    assert not window.recorder.state['units']
    assert window.switch_map('ozeti')
    assert window.recorder.state==before and window.settings['recording_minimum']==4


def test_recording_add_does_not_stop_active_trip(window):
    old=window.navigator
    old.active=True;old.lap=1;old.progress=123
    start=deepcopy(window.project['start']);goal=deepcopy(window.project['destination'])
    assert window.apply_recorded_roads([[[10,10],[20,10]]],'manual')>0
    assert old.active and old.lap==1 and old.progress==123
    assert window.project['start']==start and window.project['destination']==goal


def test_deleting_recorded_node_preserves_manual_edit_from_auto_extension(window,app):
    window.project['roads']=[dict(id='recorded',name='轨迹',kind='offroad',recording='auto',points=[[10,10],[15,12],[20,10]])]
    window.recorder.set_roads(window.project['roads'])
    window.remove_item(('road','recorded',1));app.processEvents()
    assert 'recording' not in window.project['roads'][0]
    window.apply_recorded_roads([[[20,10],[30,10]]],'auto')
    assert len(window.project['roads'])==2
    assert window.project['roads'][0]['points']==[[10,10],[20,10]]
