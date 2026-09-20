"""Public Windows desktop APIs only; no game hooks or injected input."""
import ctypes
from ctypes import wintypes
import os
import time
from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal, QTimer, Qt
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


def pressed_keys(keys):
    if not native_windows():return set()
    api=ctypes.WinDLL('user32',use_last_error=True).GetAsyncKeyState
    api.argtypes=[ctypes.c_int];api.restype=ctypes.c_short
    # Only the current down bit is reliable; never use the shared pressed-since bit.
    return {key for key in keys if api(key)&0x8000}


def input_ticks():
    api=ctypes.windll.kernel32.GetTickCount;api.restype=wintypes.DWORD
    return int(api())


def parse_hotkey(text):
    if not text.strip():return None
    parts=text.upper().replace(' ','').split('+');modifiers=0
    for part in parts[:-1]:
        if part=='NUM' and parts[-1]=='*':continue
        bit={'CTRL':2,'ALT':1,'SHIFT':4}.get(part)
        if bit is None or modifiers&bit:raise ValueError('使用 Ctrl / Alt / Shift 与字母、数字或 F1–F11 组合')
        modifiers|=bit
    key=parts[-1]
    if not modifiers&3 and key!='*':raise ValueError('字母、数字与方括号需搭配 Ctrl 或 Alt；小键盘 * 可单独使用')
    if len(key)==1 and key in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':vk=ord(key)
    elif key in ('[',']','*'):vk={'[':0xDB,']':0xDD,'*':0x6A}[key]
    elif key.startswith('F') and key[1:].isdigit() and 1<=int(key[1:])<=11:vk=111+int(key[1:])
    else:raise ValueError('按键支持字母、数字、[、]、* 或 F1–F11')
    return modifiers|0x4000,vk  # MOD_NOREPEAT


def hotkey_bindings(text):
    binding=parse_hotkey(text)
    if binding is None:return []
    # Qt records both keypad multiply and Shift+8 as '*'. Accept both forms.
    return [binding,(binding[0]|4,ord('8'))] if binding[1]==0x6A else [binding]


class _NativeFilter(QAbstractNativeEventFilter):
    def __init__(self,owner):super().__init__();self.owner=owner

    def nativeEventFilter(self,event_type,message):
        if bytes(event_type) not in (b'windows_generic_MSG',b'windows_dispatcher_MSG'):return False,0
        msg=wintypes.MSG.from_address(int(message))
        if msg.message==0x0312 and msg.wParam in self.owner.registered:
            self.owner.native_trigger(msg.wParam,msg.time);return True,0
        return False,0


class GlobalHotkeys(QObject):
    triggered=Signal(str)
    status=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent);self.registered={};self.bindings={};self.active=False
        self.poll_bindings={};self.held=set();self.last_poll={};self.poll_ready=False
        self.enabled_when=lambda:False;self.last_event=None
        self.poll_timer=QTimer(self);self.poll_timer.setTimerType(Qt.PreciseTimer);self.poll_timer.setInterval(20)
        self.poll_timer.timeout.connect(self.poll)
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
            try:bindings=hotkey_bindings(self.bindings.get(action,''))
            except ValueError as error:errors.append(f'{label}：{error}');continue
            for alias,binding in enumerate(bindings):
                if binding in used:errors.append(f'{label}：按键重复');continue
                used.add(binding);ident=0x6400+index+alias*len(ACTIONS)
                if api.RegisterHotKey(None,ident,*binding):
                    self.registered[ident]=action;self.poll_bindings[ident]=binding
                else:errors.append(f'{label}：按键已被占用或无法注册')
        if self.registered:self.poll_timer.start()
        self.status.emit('；'.join(errors) if errors else '大地图快捷键已启用')

    def emit_action(self,action,source):
        self.last_event=dict(action=action,source=source,received_at=time.time())
        self.triggered.emit(action)

    def native_trigger(self,ident,timestamp):
        action=self.registered.get(ident)
        if not self.active or action is None:return
        # WM_HOTKEY can reach Qt after polling already handled this press.
        previous=self.last_poll.get(action)
        if previous is not None and ((previous-timestamp)&0xFFFFFFFF)<250:return
        self.held.add(action);self.emit_action(action,'native')

    def poll(self):
        if not self.active or not self.enabled_when():
            self.held.clear();self.poll_ready=False;return
        keys={0x10,0x11,0x12,0x5B,0x5C}|{vk for _,vk in self.poll_bindings.values()}
        down=pressed_keys(keys)
        modifiers=sum(bit for vk,bit in ((0x12,1),(0x11,2),(0x10,4)) if vk in down)
        held={self.registered[ident] for ident,(mods,vk) in self.poll_bindings.items()
              if vk in down and modifiers==(mods&7) and not down&{0x5B,0x5C}}
        new=held-self.held if self.poll_ready else set()
        self.held=held;self.poll_ready=True
        for action in new:
            self.last_poll[action]=input_ticks();self.emit_action(action,'key_state')

    def unregister(self):
        self.poll_timer.stop();self.poll_bindings.clear();self.held.clear();self.last_poll.clear();self.poll_ready=False
        if native_windows():
            api=ctypes.WinDLL('user32',use_last_error=True).UnregisterHotKey
            api.argtypes=[wintypes.HWND,ctypes.c_int];api.restype=wintypes.BOOL
            for ident in self.registered:api(None,ident)
        self.registered.clear()

    def close(self):
        self.set_active(False)
        QApplication.instance().removeNativeEventFilter(self.filter)
