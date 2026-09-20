import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from wardogs_nav.hotkeys import GlobalHotkeys,hotkey_bindings


@pytest.fixture
def keys(monkeypatch):
    app=QApplication.instance() or QApplication([])
    keys=GlobalHotkeys();keys.active=True;keys.enabled_when=lambda:True
    values={'down':set(),'tick':1000,'reads':0}
    def read(requested):values['reads']+=1;return values['down']&requested
    monkeypatch.setattr('wardogs_nav.hotkeys.pressed_keys',read)
    monkeypatch.setattr('wardogs_nav.hotkeys.input_ticks',lambda:values['tick'])
    for ident,binding in enumerate(hotkey_bindings('Ctrl+Alt+D')):
        keys.registered[ident]='destination';keys.poll_bindings[ident]=binding
    events=[];keys.triggered.connect(events.append)
    yield keys,values,events
    keys.close();app.processEvents()


def test_key_state_fallback_catches_repeated_presses_without_native_messages(keys):
    keys,values,events=keys
    keys.poll()
    for _ in range(3):
        values['down']={0x11,0x12,ord('D')};values['tick']+=100
        keys.poll();keys.poll()
        values['down']={0x11,0x12};keys.poll()
    assert events==['destination']*3
    assert keys.last_event['source']=='key_state'


def test_native_and_polling_do_not_double_dispatch_same_press(keys):
    keys,values,events=keys;keys.poll()
    values['down']={0x11,0x12,ord('D')};keys.poll()
    keys.native_trigger(0,values['tick']-5)
    values['down']=set();keys.poll()
    keys.native_trigger(0,values['tick']-5)  # Delayed WM_HOTKEY after release.
    assert events==['destination']
    values['tick']+=500;keys.native_trigger(0,values['tick'])
    values['down']={0x11,0x12,ord('D')};keys.poll()
    assert events==['destination']*2


def test_polling_stops_outside_active_game_map_and_ignores_held_entry(keys):
    keys,values,events=keys;keys.enabled_when=lambda:False
    values['down']={0x11,0x12,ord('D')};keys.poll()
    assert values['reads']==0
    keys.enabled_when=lambda:True;keys.poll();keys.poll()
    assert not events
    values['down']=set();keys.poll()
    values['down']={0x11,0x12,ord('D')};keys.poll()
    assert events==['destination']
    keys.set_active(False);before=values['reads'];keys.poll()
    assert values['reads']==before and not keys.poll_timer.isActive()


@pytest.mark.parametrize('text,down',[('*',{0x6A}),('*',{0x10,ord('8')}),('Ctrl+*',{0x11,0x6A}),
    ('Ctrl+*',{0x11,0x10,ord('8')}),('Ctrl+Alt+[',{0x11,0x12,0xDB}),('Ctrl+Alt+]',{0x11,0x12,0xDD})])
def test_symbol_bindings_through_production_poll(keys,text,down):
    keys,values,events=keys;keys.registered.clear();keys.poll_bindings.clear()
    for ident,binding in enumerate(hotkey_bindings(text)):
        keys.registered[ident]='destination';keys.poll_bindings[ident]=binding
    keys.poll();values['down']=down;keys.poll();keys.poll()
    assert events==['destination']


def test_extra_modifiers_do_not_fire_a_different_binding(keys):
    keys,values,events=keys;keys.poll()
    values['down']={0x10,0x11,0x12,ord('D')};keys.poll()
    values['down']={0x5B,0x11,0x12,ord('D')};keys.poll()
    assert not events
