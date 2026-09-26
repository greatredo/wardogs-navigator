"""Keep wheel scrolling out of settings controls, including Qt input dialogs."""
from PySide6.QtCore import QObject,QEvent
from PySide6.QtWidgets import QApplication,QAbstractSpinBox,QComboBox,QAbstractScrollArea


class SettingsWheelFilter(QObject):
    def eventFilter(self,watched,event):
        if event.type()!=QEvent.Wheel:return False
        control=watched if isinstance(watched,(QAbstractSpinBox,QComboBox)) else watched.parent()
        if not isinstance(control,(QAbstractSpinBox,QComboBox)):return False
        parent=control.parentWidget()
        while parent is not None:
            if isinstance(parent,QAbstractScrollArea):
                QApplication.sendEvent(parent.viewport(),event)
                return True
            parent=parent.parentWidget()
        return True


def protect_settings_wheel():
    app=QApplication.instance()
    if not hasattr(app,'settings_wheel_filter'):
        app.settings_wheel_filter=SettingsWheelFilter(app)
        app.installEventFilter(app.settings_wheel_filter)
