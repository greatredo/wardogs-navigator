from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QPen
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QCheckBox,
    QDialogButtonBox,QDoubleSpinBox,QSpinBox,QLabel,QWidget,QPushButton,QHBoxLayout)
from .model import KINDS, NOTE_TYPES, MODIFIERS
from .navigation import Cue, cue_text


def number(value, low, high, decimals=0):
    widget=QDoubleSpinBox() if decimals else QSpinBox()
    widget.setRange(low,high)
    if decimals:
        widget.setDecimals(decimals)
    widget.setValue(value)
    return widget


class RoadDialog(QDialog):
    def __init__(self, road, parent=None):
        super().__init__(parent)
        self.setWindowTitle('道路属性');self.setMinimumWidth(440)
        layout=QVBoxLayout(self);form=QFormLayout()
        self.name=QLineEdit(road.get('name','新道路'))
        self.kind=QComboBox()
        for value,label in KINDS.items():self.kind.addItem(label,value)
        self.kind.setCurrentIndex(self.kind.findData(road.get('kind','minor')))
        self.confirmed=QCheckBox('已在游戏内确认可通行');self.confirmed.setChecked(road.get('confirmed',False))
        self.note=QLineEdit(road.get('note',''))
        form.addRow('名称',self.name);form.addRow('分类',self.kind);form.addRow('',self.confirmed);form.addRow('备注',self.note)
        layout.addLayout(form)
        label=QLabel('图片只能提供候选；请结合路宽、树木、坡度与桥梁实测。');label.setWordWrap(True);layout.addWidget(label)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def values(self):
        return dict(name=self.name.text().strip() or '未命名道路',kind=self.kind.currentData(),confirmed=self.confirmed.isChecked(),note=self.note.text())


class FavoriteImportDialog(QDialog):
    def __init__(self,routes,parent=None):
        super().__init__(parent);self.setWindowTitle('导入路线收藏');self.setMinimumWidth(470)
        layout=QVBoxLayout(self)
        label=QLabel(f'将合并 {len(routes)} 条收藏。原有收藏、目的地和危险区保留。');label.setWordWrap(True);layout.addWidget(label)
        self.snap=QCheckBox('贴合现有道路（重新计算路线）');layout.addWidget(self.snap)
        description=QLabel('开启后，粗绘点之间沿当前路网规划，遵守道路规则和危险区；失败则不导入。关闭则保留文件中的完整路径。')
        description.setWordWrap(True);layout.addWidget(description)
        self.road_action=QComboBox()
        self.road_action.addItem('请确认是否按路线建立道路…','choose')
        self.road_action.addItem('是：将缺失路段补入公共路网',True)
        self.road_action.addItem('否：仅供收藏导航，不加入公共路网',False)
        if routes and all('build_roads' in saved for saved in routes):
            builds=sum(saved['build_roads'] for saved in routes)
            self.road_action.addItem(f'沿用文件设置（{builds} 条建路，{len(routes)-builds} 条仅收藏）','stored')
            self.road_action.setCurrentIndex(3)
        layout.addWidget(QLabel('不贴合时，是否按照路线建立道路？'));layout.addWidget(self.road_action)
        note=QLabel('不建立道路也可按原路线导航；缺路仅在该收藏行程中使用，仍受分类、实测过滤和危险区约束。建立的道路标为待实测，可撤销本次导入。')
        note.setWordWrap(True);layout.addWidget(note)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('确认导入')
        self.buttons.button(QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        self.snap.toggled.connect(self.update_options);self.road_action.currentIndexChanged.connect(self.update_options);self.update_options()

    def update_options(self,*_):
        self.road_action.setEnabled(not self.snap.isChecked())
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(self.snap.isChecked() or self.road_action.currentData()!='choose')

    def options(self):
        action=self.road_action.currentData()
        return dict(snap_to_roads=self.snap.isChecked(),build_roads=None if action=='stored' else action if isinstance(action,bool) else False)


class NoteDialog(QDialog):
    def __init__(self,note=None,parent=None):
        super().__init__(parent)
        self.setWindowTitle('WRC 路书标注');self.setMinimumWidth(470)
        note=note or {};layout=QVBoxLayout(self);form=QFormLayout()
        self.kind=QComboBox()
        for value,label in NOTE_TYPES.items():self.kind.addItem(label,value)
        self.kind.setCurrentIndex(max(0,self.kind.findData(note.get('type','left'))))
        self.grade=number(note.get('grade',4),1,6)
        self.direction=QComboBox()
        for label,value in [('双向（反向自动交换左右）','both'),('仅正向','forward'),('仅反向','reverse')]:self.direction.addItem(label,value)
        self.direction.setCurrentIndex(max(0,self.direction.findData(note.get('direction','both'))))
        self.bearing=number(note.get('bearing',0),0,359)
        self.lead=number(note.get('lead_m',0),0,2000)
        self.text=QLineEdit(note.get('text',''));self.text.setPlaceholderText('留空使用“左4”等标准播报')
        self.reverse=QLineEdit(note.get('reverse_text',''));self.reverse.setPlaceholderText('反向专用文字；留空按类型自动播报')
        form.addRow('类型',self.kind);form.addRow('弯级（1 慢 / 6 快）',self.grade);form.addRow('适用方向',self.direction)
        form.addRow('正向驶入方位（北0 / 东90）',self.bearing);form.addRow('提前距离（米；0用全局）',self.lead)
        form.addRow('正向播报文字',self.text);form.addRow('反向播报文字',self.reverse);layout.addLayout(form)
        self.modifiers={}
        modifier_row=QHBoxLayout()
        for key,label in MODIFIERS.items():
            box=QCheckBox(label);box.setChecked(key in note.get('modifiers',[]));self.modifiers[key]=box
            box.toggled.connect(self.update_preview);modifier_row.addWidget(box)
        layout.addLayout(modifier_row)
        self.preview=QLabel();self.preview.setWordWrap(True);layout.addWidget(self.preview)
        for control in (self.kind,self.grade,self.text):
            signal=control.currentIndexChanged if isinstance(control,QComboBox) else control.valueChanged if hasattr(control,'valueChanged') else control.textChanged
            signal.connect(self.update_preview)
        self.update_preview()
        if parent is not None and hasattr(parent,'speak'):
            audition=QPushButton('试听此条路书');audition.clicked.connect(lambda:parent.speak(self.preview.text()));layout.addWidget(audition)
        hint=QLabel('先将标注放在行驶路线上。方向以驶入该点的车头方向为准；提前秒数仍与提前距离叠加。');hint.setWordWrap(True);layout.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def values(self):
        return dict(type=self.kind.currentData(),grade=self.grade.value(),direction=self.direction.currentData(),bearing=self.bearing.value(),lead_m=self.lead.value(),text=self.text.text().strip(),reverse_text=self.reverse.text().strip(),modifiers=[k for k,w in self.modifiers.items() if w.isChecked()])

    def update_preview(self,*_):
        if not hasattr(self,'preview'):return
        self.grade.setEnabled(self.kind.currentData() in ('left','right'))
        cue=Cue('preview',0,self.kind.currentData(),self.grade.value(),self.text.text().strip(),
                modifiers=[k for k,w in self.modifiers.items() if w.isChecked()])
        self.preview.setText(cue_text(cue,'wrc',spoken=True))


class RegionCanvas(QWidget):
    selected=Signal(object)

    def __init__(self,image):
        super().__init__();self.pixmap=QPixmap.fromImage(image);self.start=None;self.end=None
        self.setMinimumSize(640,360)
        self.setMouseTracking(True)

    def display_rect(self):
        size=self.pixmap.size();size.scale(self.size(),Qt.KeepAspectRatio)
        return QRect((self.width()-size.width())//2,(self.height()-size.height())//2,size.width(),size.height())

    def mousePressEvent(self,e):
        self.start=e.position().toPoint();self.end=self.start;self.update()

    def mouseMoveEvent(self,e):
        if self.start is not None and e.buttons()&Qt.LeftButton:self.end=e.position().toPoint();self.update()

    def mouseReleaseEvent(self,e):
        self.end=e.position().toPoint()
        bounds=self.display_rect();r=QRect(self.start,self.end).normalized().intersected(bounds)
        sx=self.pixmap.width()/bounds.width();sy=self.pixmap.height()/bounds.height()
        result={'left':round((r.left()-bounds.left())*sx),'top':round((r.top()-bounds.top())*sy),'width':round(r.width()*sx),'height':round(r.height()*sy)}
        if result['width']>=60 and result['height']>=60:self.selected.emit(result)
        self.update()

    def paintEvent(self,e):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#10161c'));p.drawPixmap(self.display_rect(),self.pixmap)
        if self.start is not None and self.end is not None:
            p.setPen(QPen(QColor('#67e6c3'),2));p.setBrush(QColor(50,220,170,30));p.drawRect(QRect(self.start,self.end).normalized())


class RegionDialog(QDialog):
    def __init__(self,frame,monitor,parent=None):
        super().__init__(parent);self.setWindowTitle('框选小地图 · 只包含地图画面，尽量让玩家箭头居中')
        self.resize(1120,740);self.monitor=monitor;self.region=None
        rgb=frame[:,:,::-1].copy();h,w=rgb.shape[:2]
        image=QImage(rgb.data,w,h,rgb.strides[0],QImage.Format_RGB888).copy()
        layout=QVBoxLayout(self);layout.addWidget(QLabel('拖动框选左下角小地图。数值使用屏幕物理像素，可兼容 DPI 缩放。'))
        self.canvas=RegionCanvas(image);self.canvas.selected.connect(self.select);layout.addWidget(self.canvas,1)
        self.label=QLabel('尚未选择区域');layout.addWidget(self.label)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);self.ok=buttons.button(QDialogButtonBox.Ok);self.ok.setEnabled(False)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def select(self,r):
        self.region=dict(r,left=r['left']+self.monitor['left'],top=r['top']+self.monitor['top'])
        self.label.setText(f"屏幕位置 {self.region['left']}, {self.region['top']}  ·  {r['width']} × {r['height']}")
        self.ok.setEnabled(True)
