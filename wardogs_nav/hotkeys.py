"""Public Windows desktop APIs only; no game hooks or injected input."""
import ctypes
from ctypes import wintypes
import os
from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QApplication
from .overlay import native_windows


ACTIONS={'navigate':'一键新导航','destination':'修改目的地','start':'修改起始点 / 返程终点',
         'waypoint':'添加途经点','avoid':'添加危险区','undo':'撤销标注','clear':'清除当前路线'}
DEFAULT_HOTKEYS=dict(zip(ACTIONS,('Ctrl+Alt+N','Ctrl+Alt+D','Ctrl+Alt+S','Ctrl+Alt+W',
                                 'Ctrl+Alt+A','Ctrl+Alt+Z','Ctrl+Alt+C')))


def foreground_window():
    if not native_windows():return 0
    api=ctypes.WinDLL('user32',use_last_error=True)
    api.GetForegroundWindow.restype=wintypes.HWND
    hwnd=api.GetForegroundWindow()
    pid=wintypes.DWORD()
    api.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    return int(hwnd or 0) if pid.value!=os.getpid() else 0


def physical_cursor():
    if not native_windows():return None
    api=ctypes.WinDLL('user32',use_last_error=True).GetPhysicalCursorPos
    api.argtypes=[ctypes.POINTER(wintypes.POINT)];api.restype=wintypes.BOOL
    point=wintypes.POINT()
    return (point.x,point.y) if api(ctypes.byref(point)) else None


def parse_hotkey(text):
    if not text.strip():return None
    parts=text.upper().replace(' ','').split('+');modifiers=0
    for part in parts[:-1]:
        bit={'CTRL':2,'ALT':1,'SHIFT':4}.get(part)
        if bit is None or modifiers&bit:raise ValueError('使用 Ctrl / Alt / Shift 与字母、数字或 F1–F11 组合')
        modifiers|=bit
    key=parts[-1]
    if not modifiers&3:raise ValueError('快捷键至少包含 Ctrl 或 Alt')
    if len(key)==1 and key in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':vk=ord(key)
    elif key.startswith('F') and key[1:].isdigit() and 1<=int(key[1:])<=11:vk=111+int(key[1:])
    else:raise ValueError('按键支持字母、数字或 F1–F11')
    return modifiers|0x4000,vk  # MOD_NOREPEAT


class _NativeFilter(QAbstractNativeEventFilter):
    def __init__(self,owner):super().__init__();self.owner=owner

    def nativeEventFilter(self,event_type,message):
        if bytes(event_type) not in (b'windows_generic_MSG',b'windows_dispatcher_MSG'):return False,0
        msg=wintypes.MSG.from_address(int(message))
        if msg.message==0x0312 and msg.wParam in self.owner.registered:
            self.owner.triggered.emit(self.owner.registered[msg.wParam]);return True,0
        return False,0


class GlobalHotkeys(QObject):
    triggered=Signal(str)
    status=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent);self.registered={};self.bindings={};self.active=False
        self.filter=_NativeFilter(self)
        QApplication.instance().installNativeEventFilter(self.filter)

    def configure(self,bindings):
        self.bindings=dict(bindings)
        if self.active:self.set_active(False);self.set_active(True)

    def set_active(self,active):
        if self.active==active:return
        self.unregister();self.active=active
        if not active:return
        if not native_windows():self.status.emit('全局快捷键需要 Windows 桌面');return
        api=ctypes.WinDLL('user32',use_last_error=True)
        api.RegisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT]
        api.RegisterHotKey.restype=wintypes.BOOL
        used=set();errors=[]
        for index,(action,label) in enumerate(ACTIONS.items()):
            try:binding=parse_hotkey(self.bindings.get(action,''))
            except ValueError as error:errors.append(f'{label}：{error}');continue
            if binding is None:continue
            if binding in used:errors.append(f'{label}：按键重复');continue
            used.add(binding);ident=0x6400+index
            if api.RegisterHotKey(None,ident,*binding):self.registered[ident]=action
            else:errors.append(f'{label}：按键已被占用或无法注册')
        self.status.emit('；'.join(errors) if errors else '大地图快捷键已启用')

    def unregister(self):
        if native_windows():
            api=ctypes.WinDLL('user32',use_last_error=True).UnregisterHotKey
            api.argtypes=[wintypes.HWND,ctypes.c_int];api.restype=wintypes.BOOL
            for ident in self.registered:api(None,ident)
        self.registered.clear()

    def close(self):
        self.set_active(False)
        QApplication.instance().removeNativeEventFilter(self.filter)
