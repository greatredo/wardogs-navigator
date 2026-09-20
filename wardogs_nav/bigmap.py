"""Click-through large-map annotations in physical capture coordinates."""
import math
import numpy as np
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QColor,QImage,QPainter,QPainterPath,QPen,QFont
from PySide6.QtWidgets import QWidget
from .overlay import native_windows,keep_on_top,exclude_from_capture
from .routing import remaining_points
from .model import NOTE_TYPES


class BigMapOverlay(QWidget):
    mask_changed=Signal(object)

    def __init__(self,settings):
        super().__init__();self.settings=settings;self.surface=None;self.capture_excluded=None;self.region=None;self.opacity=None
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool|Qt.WindowTransparentForInput|Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground);self.setAttribute(Qt.WA_ShowWithoutActivating)

    def render_annotations(self,view,project,route,full_route,progress,vehicle,message):
        w,h=view.frame_size
        image=QImage(w,h,QImage.Format_RGBA8888);image.fill(Qt.transparent)
        p=QPainter(image);p.setRenderHint(QPainter.Antialiasing);p.setFont(QFont('Microsoft YaHei UI',10))

        def path(points,color,width):
            points=view.project(points)
            if len(points)<2:return
            curve=QPainterPath(QPointF(*points[0]))
            for xy in points[1:]:curve.lineTo(*xy)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(8,25,27,color.alpha()),width+2,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin));p.drawPath(curve)
            p.setPen(QPen(color,width,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin));p.drawPath(curve)

        def marker(point,label,color,radius=6):
            if point is None:return
            x,y=view.project([point])[0]
            if not (-20<x<w+20 and -20<y<h+20):return
            p.setPen(QPen(QColor('#101d26'),3));p.setBrush(QColor(color));p.drawEllipse(QPointF(x,y),radius,radius)
            p.setPen(QColor('#101d26'));p.drawText(QPointF(x+10,y+1),label)
            p.setPen(QColor(color));p.drawText(QPointF(x+9,y),label)

        for zone in project['avoid']:
            x,y=zone['point']
            if zone.get('shape')=='rect':
                dx,dy=zone['width']/2,zone['height']/2
                points=[[x-dx,y-dy],[x+dx,y-dy],[x+dx,y+dy],[x-dx,y+dy],[x-dx,y-dy]]
            else:
                points=[[x+zone['radius']*math.cos(a),y+zone['radius']*math.sin(a)] for a in np.linspace(0,2*math.pi,65)]
            path(points,QColor('#ff827e'),2)
            marker(zone['point'],'危险区','#ff827e',4)
        complete=full_route or route
        if complete:path(complete.points,QColor(103,237,195,85),self.settings['line_width'])
        if route:path(remaining_points(route,progress),QColor('#67edc3'),self.settings['line_width'])
        for note in project['notes']:
            marker(note['point'],note.get('text') or NOTE_TYPES[note['type']],'#d6b1fa',4)
        for destination in project['destinations']:
            marker(destination['point'],destination['name'],'#c6ad73',4)
        for i,point in enumerate(project['waypoints']):marker(point,f'途经 {i+1}','#80ecaa')
        marker(project.get('start'),'起始点 / 返程终点','#78caff',8)
        marker(project.get('destination'),'目的地','#ffce70',8)
        marker(vehicle,'上次车辆位置','#dce7eb',5)
        p.setPen(Qt.NoPen);p.setBrush(QColor(15,28,36,225));p.drawRoundedRect(8,8,max(200,min(w-16,p.fontMetrics().horizontalAdvance(message)+22)),30,5,5)
        p.setPen(QColor('#d9f4e9'));p.drawText(QPointF(18,29),message)
        p.end()
        return image

    def update_map(self,view,project,route=None,full_route=None,progress=0,vehicle=None,message='大地图 · 可使用快捷键'):
        if not view or not view.valid:self.hide();return
        self.surface=self.render_annotations(view,project,route,full_route,progress,vehicle,message)
        opacity=float(self.settings['opacity'])
        if self.opacity!=opacity:self.setWindowOpacity(opacity);self.opacity=opacity
        showing=not self.isVisible()
        if showing:self.show()
        if self.capture_excluded is None:self.capture_excluded=exclude_from_capture(self)
        if showing or self.region!=view.region:
            if native_windows():keep_on_top(self,view.region)
            else:self.setGeometry(*[view.region[k] for k in ('left','top','width','height')])
            self.region=dict(view.region)
        mask=None
        if not self.capture_excluded:
            pixels=np.frombuffer(self.surface.constBits(),np.uint8).reshape(self.surface.height(),self.surface.bytesPerLine())
            mask=pixels[:,:self.surface.width()*4].reshape(self.surface.height(),self.surface.width(),4)[:,:,3].copy()
        self.mask_changed.emit(mask);self.update()

    def hideEvent(self,event):
        self.mask_changed.emit(None);super().hideEvent(event)

    def paintEvent(self,event):
        if self.surface is not None:
            painter=QPainter(self);painter.drawImage(self.rect(),self.surface)
