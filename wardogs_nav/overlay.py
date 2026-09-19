"""Small OS windows; no game process handles or graphics hooks."""
import ctypes
from ctypes import wintypes
import math
import sys
from PySide6.QtCore import Qt, QPointF,Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor
from PySide6.QtWidgets import QWidget, QApplication
from .routing import remaining_points


def native_windows():
    return sys.platform=='win32' and QApplication.platformName()=='windows'


def exclude_from_capture(widget):
    # Older Windows treats 0x11 as blacking out the entire window rectangle.
    if not native_windows() or sys.getwindowsversion().build<19041:return False
    api=ctypes.WinDLL('user32',use_last_error=True).SetWindowDisplayAffinity
    api.argtypes=[wintypes.HWND,wintypes.DWORD];api.restype=wintypes.BOOL
    result=bool(api(int(widget.winId()),0x11))
    widget.capture_exclusion_error=0 if result else ctypes.get_last_error()
    return result


def keep_on_top(widget,region=None):
    if not native_windows():return
    api=ctypes.WinDLL('user32',use_last_error=True).SetWindowPos
    api.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    api.restype=wintypes.BOOL
    flags=0x0010|0x0040  # NOACTIVATE | SHOWWINDOW
    if region is None:
        if not widget.isVisible():return
        flags|=0x0001|0x0002  # NOSIZE | NOMOVE
        region={'left':0,'top':0,'width':0,'height':0}
    api(int(widget.winId()),wintypes.HWND(-1),*[int(region[k]) for k in ('left','top','width','height')],flags)


def project_to_minimap(points,fix,frame_size,anchor):
    """Invert the accepted similarity transform, keeping physical capture pixels."""
    if not fix or not fix.valid or fix.scale<=0:return []
    theta=math.radians(fix.rotation);c,s=math.cos(theta),math.sin(theta)
    w,h=frame_size
    return [((c*(x-fix.x)+s*(y-fix.y))/fix.scale+anchor[0]*w,
             (-s*(x-fix.x)+c*(y-fix.y))/fix.scale+anchor[1]*h) for x,y in points]


class MinimapOverlay(QWidget):
    mask_changed=Signal(object)
    def __init__(self,settings):
        super().__init__()
        self.settings=settings;self.points=[];self.full_points=[];self.frame_size=(1,1);self.capture_excluded=None
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool|Qt.WindowTransparentForInput|Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground);self.setAttribute(Qt.WA_ShowWithoutActivating)

    def update_route(self,route,fix,frame_size,anchor,region,*,full_route=None,progress=0.):
        full_route=full_route or route
        self.full_points=project_to_minimap(full_route.points,fix,frame_size,anchor) if full_route else []
        self.points=project_to_minimap(remaining_points(route,progress),fix,frame_size,anchor)
        if not self.settings['enabled'] or not self.full_points:self.hide();return
        self.frame_size=frame_size
        # DWM must have a shown top-level surface before applying affinity.
        self.setWindowOpacity(float(self.settings['opacity']))
        self.show()
        if self.capture_excluded is None:self.capture_excluded=exclude_from_capture(self)
        # Some Windows/driver combinations reject display affinity on layered
        # windows (error 8). The locator also masks the saturated path colour,
        # including its outline, so navigation remains usable in that case.
        if native_windows():keep_on_top(self,region)
        else:self.setGeometry(region['left'],region['top'],region['width'],region['height'])
        self.mask_changed.emit({'paths':[list(self.full_points),list(self.points)],'width':self.settings['line_width']})
        self.update()

    def hideEvent(self,event):
        self.mask_changed.emit(None)
        super().hideEvent(event)

    def paintEvent(self,event):
        if len(self.full_points)<2:return
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.width()/self.frame_size[0],self.height()/self.frame_size[1])
        width=float(self.settings['line_width'])
        for points,outline,color in ((self.full_points,QColor(8,25,27,90),QColor(103,237,195,85)),
                                     (self.points,QColor(8,25,27,210),QColor('#67edc3'))):
            if len(points)<2:continue
            path=QPainterPath(QPointF(*points[0]))
            for xy in points[1:]:path.lineTo(*xy)
            p.setPen(QPen(outline,width+2,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin));p.drawPath(path)
            p.setPen(QPen(color,width,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin));p.drawPath(path)
