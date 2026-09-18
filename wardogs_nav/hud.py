from PySide6.QtCore import Qt, QPoint, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QPainterPath
from PySide6.QtWidgets import QWidget, QApplication
from .overlay import exclude_from_capture,keep_on_top
from .navigation import cue_text
from .model import MODIFIERS


def draw_symbol(p, rect, kind, color):
    p.save()
    p.translate(rect.center())
    size=min(rect.width(),rect.height())/80
    p.scale(size,size)
    p.setPen(QPen(QColor(color),8,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    if kind in ('left','right','hairpin_left','hairpin_right','square_left','square_right','keep_left','keep_right','uturn'):
        flip=-1 if 'left' in kind else 1
        p.scale(flip,1)
        path=QPainterPath()
        path.moveTo(-12,27)
        if 'hairpin' in kind or kind=='uturn':
            path.lineTo(-12,-12); path.cubicTo(-12,-38,23,-38,23,-12); path.lineTo(23,15)
            p.drawPath(path); p.drawLine(23,15,12,4); p.drawLine(23,15,33,4)
        elif 'square' in kind:
            path.lineTo(-12,-18);path.lineTo(26,-18)
            p.drawPath(path);p.drawLine(26,-18,13,-30);p.drawLine(26,-18,13,-6)
        elif 'keep' in kind:
            path.lineTo(-12,0);path.lineTo(22,-26)
            p.drawPath(path);p.drawLine(22,-26,6,-25);p.drawLine(22,-26,21,-10)
        else:
            path.lineTo(-12,-3); path.quadTo(-12,-18,4,-18); path.lineTo(26,-18)
            p.drawPath(path); p.drawLine(26,-18,13,-30); p.drawLine(26,-18,13,-6)
    elif kind in ('caution','water','narrow','bridge','crest','jump','bump','brake','hard_brake'):
        p.setFont(QFont('Microsoft YaHei UI',38,QFont.Bold))
        p.drawText(QRectF(-40,-40,80,80),Qt.AlignCenter,{'caution':'!','water':'≈','narrow':'><','bridge':'╫','crest':'⌒','jump':'↗','bump':'∿','brake':'!','hard_brake':'!!'}[kind])
    elif kind == 'arrival':
        p.drawLine(-18,30,-18,-30)
        p.drawLine(-18,-27,24,-27);p.drawLine(24,-27,24,-4);p.drawLine(24,-4,-18,-4)
    else:
        p.drawLine(0,28,0,-28);p.drawLine(0,-28,-16,-12);p.drawLine(0,-28,16,-12)
    p.restore()


class Hud(QWidget):
    changed=Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings=settings
        self.data={'text':'等待定位','state':'idle'}
        self.mode='normal'
        self.drag=None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.apply_settings()

    def apply_settings(self):
        s=self.settings
        flags=Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        if s.get('locked'):
            flags |= Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        was_visible=self.isVisible()
        self.setWindowFlags(flags)
        self.setGeometry(int(s['x']),int(s['y']),max(240,int(s['width'])),max(110,int(s['height'])))
        self.setWindowOpacity(float(s.get('opacity',.94)))
        if was_visible:
            self.show()

    def set_data(self,data,mode='normal',calibrated=True):
        self.data=data or {'text':'等待路线','state':'idle'}
        self.mode=mode
        self.calibrated=calibrated
        self.update()

    def showEvent(self,event):
        super().showEvent(event)
        exclude_from_capture(self)
        keep_on_top(self)

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.drag=event.globalPosition().toPoint()-self.pos()

    def mouseMoveEvent(self,event):
        if self.drag is not None:
            self.move(event.globalPosition().toPoint()-self.drag)

    def mouseReleaseEvent(self,event):
        self.drag=None
        self.settings.update(x=self.x(),y=self.y())
        self.changed.emit()

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#365147'),1))
        p.setBrush(QColor(14,24,28,244))
        p.drawRoundedRect(self.rect().adjusted(1,1,-1,-1),16,16)
        scale=min(self.width()/400,self.height()/170)
        p.scale(scale,scale)
        w=self.width()/scale
        if self.mode=='wrc' and self.data.get('upcoming') and self.data.get('state')=='navigating':
            self.paint_roadbook(p,w)
            return
        cue=self.data.get('cue')
        kind=cue.kind if cue else 'straight'
        color='#e8c570' if self.mode=='wrc' else '#66e6c3'
        draw_symbol(p,QRectF(14,47,82,85),'straight' if self.data.get('text')=='沿当前道路行驶' else kind,color)
        p.setPen(QColor('#a3b4b7'));p.setFont(QFont('Microsoft YaHei UI',9))
        p.drawText(QRectF(20,10,w-35,26),Qt.AlignLeft|Qt.AlignVCenter,'WARDOGS  /  '+('WRC 路书' if self.mode=='wrc' else '地面导航')+'   '+self.data.get('leg',''))
        text=self.data.get('text','等待定位')
        if cue and self.mode=='wrc' and kind in ('left','right'):
            text=('左' if kind=='left' else '右')+f' {cue.grade}'
        p.setFont(QFont('Microsoft YaHei UI',23 if len(text)<10 else 13,QFont.Bold))
        p.setPen(QColor('#f0f4f3'))
        p.drawText(QRectF(110,44,w-125,55),Qt.AlignLeft|Qt.AlignVCenter,text)
        p.setFont(QFont('Microsoft YaHei UI',11))
        p.setPen(QColor(color))
        d=self.data.get('distance')
        unit='米' if getattr(self,'calibrated',True) else '单位'
        sub=f'{d:.0f} {unit}' if d is not None else '自动定位 · 本地导航'
        remaining=self.data.get('remaining')
        if remaining is not None:
            sub+=f'   /   剩余 {remaining/1000:.2f} km' if unit=='米' else f'  /  剩余 {remaining:.0f}'
        p.drawText(QRectF(110,103,w-125,30),Qt.AlignLeft,sub)
        p.setFont(QFont('Microsoft YaHei UI',8));p.setPen(QColor('#9da8ab'))
        footer=self.data.get('next_text','按规划道路行驶') if self.mode=='normal' else '路书 · 1 慢弯 — 6 快弯'
        if not self.settings.get('locked'):
            footer+='  ·  可拖动'
        p.drawText(QRectF(20,142,w-35,22),Qt.AlignLeft,footer)

    def paint_roadbook(self,p,w):
        p.setFont(QFont('Microsoft YaHei UI',9));p.setPen(QColor('#e8c570'))
        p.drawText(QRectF(16,8,w-32,22),Qt.AlignLeft,'WRC  /  路书    '+self.data.get('leg',''))
        cards=self.data['upcoming'][:3];width=(w-32-8*(len(cards)-1))/len(cards)
        unit='m' if getattr(self,'calibrated',True) else '单位'
        for i,item in enumerate(cards):
            cue=item['cue'];x=16+i*(width+8)
            color='#ff8e79' if cue.kind in ('hard_brake','brake','caution') else '#e8c570' if i==0 else '#b4c4c9'
            p.setPen(QPen(QColor('#66563b' if i==0 else '#35424a'),1));p.setBrush(QColor('#2c302b' if i==0 else '#19252d'))
            p.drawRoundedRect(QRectF(x,34,width,103),7,7)
            draw_symbol(p,QRectF(x+5,40,min(55,width*.45),55),cue.kind,color)
            label=str(cue.grade) if cue.kind in ('left','right') else cue_text(cue,'wrc').split('，')[0]
            p.setPen(QColor(color));p.setFont(QFont('Microsoft YaHei UI',27 if label.isdigit() else 10,QFont.Bold))
            p.drawText(QRectF(x+width*.44,40,width*.52,50),Qt.AlignCenter,label)
            p.setFont(QFont('Microsoft YaHei UI',10,QFont.Bold));p.setPen(QColor('#e8eeee'))
            p.drawText(QRectF(x+5,94,width-10,20),Qt.AlignCenter,f"{item['distance']:.0f} {unit}")
            detail=' / '.join(MODIFIERS[m] for m in cue.modifiers)
            if cue.text:detail=cue.text
            if not detail:detail='估算' if cue.inferred else '手动路书' if cue.kind!='arrival' else '终点'
            p.setFont(QFont('Microsoft YaHei UI',8));p.setPen(QColor('#aab7b8'))
            p.drawText(QRectF(x+5,116,width-10,17),Qt.AlignCenter,p.fontMetrics().elidedText(detail,Qt.ElideRight,int(width-10)))
        p.setFont(QFont('Microsoft YaHei UI',8));p.setPen(QColor('#a4b0b3'))
        remaining=self.data.get('remaining',0)
        footer=f'1 慢弯 · 6 快弯    剩余 {remaining/1000:.2f} km' if unit=='m' else f'1 慢弯 · 6 快弯    剩余 {remaining:.0f} 单位'
        if not self.settings.get('locked'):footer+='  ·  可拖动'
        p.drawText(QRectF(16,143,w-32,20),Qt.AlignLeft,footer)
