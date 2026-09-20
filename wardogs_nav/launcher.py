"""Mode selection. No pilot imports or optional dependencies in the host process."""
import json
from pathlib import Path
import sys
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QMessageBox
from .model import asset_path


def pilot_component(root=None, frozen=None):
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    root = Path(root) if root else (Path(sys.executable).parent if frozen else Path(__file__).resolve().parents[1])
    folder = root / 'components' / 'pilot' if frozen else root / 'pilot'
    try:
        manifest = json.loads((folder / 'component.json').read_text(encoding='utf-8'))
        if manifest.get('id') != 'wardogs-pilot' or manifest.get('host_api') != 1:
            return None, '飞行员组件版本不兼容，请安装匹配的组件包'
        entry = folder / ('WardogsPilot.exe' if frozen else 'main.py')
        required = folder / ('_internal' if frozen else 'wardogs_pilot')
        required_files = ([required/'PySide6/Qt6Core.dll', required/'wardogs_pilot/windows_bridge.ps1',
                           required/'assets/audio/airplane-announcement.mp3'] if frozen else
                          [required/'app.py', required/'core.py', required/'windows_bridge.ps1'])
        if (not entry.is_file() or not required.is_dir() or any(not p.is_file() for p in required_files)
                or (frozen and not any(required.glob('python3*.dll')))):
            return None, '飞行员组件不完整，请重新完整解压组件包'
        command = [str(entry)] if frozen else [sys.executable, str(entry)]
        return command + ['--host-assets', str(asset_path(''))], '已安装飞行员组件 ' + str(manifest.get('version', ''))
    except FileNotFoundError:
        return None, '尚未安装飞行员组件 · 地面导航可直接使用'
    except (OSError, ValueError, TypeError, AttributeError):
        return None, '飞行员组件清单损坏 · 地面导航可直接使用'


class ModeDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('WARDOGS · 选择模式')
        self.setMinimumWidth(510)
        self.mode = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel('今天驾驶什么？')
        title.setStyleSheet('font-size:22pt;font-weight:700')
        layout.addWidget(title)
        layout.addWidget(QLabel('两个模式分别保存设置、航线与播报。'))
        ground = QPushButton('地面导航  →  常规导航 / WRC 路书')
        ground.setMinimumHeight(65)
        ground.clicked.connect(self.ground)
        layout.addWidget(ground)
        self.command, status = pilot_component()
        self.pilot_button = QPushButton('飞行员  →  预设航线 / 客舱播报')
        self.pilot_button.setMinimumHeight(65)
        self.pilot_button.setEnabled(self.command is not None)
        self.pilot_button.clicked.connect(self.pilot)
        layout.addWidget(self.pilot_button)
        self.status = QLabel(status)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        help_text = QLabel('安装：把飞行员组件包解压到本程序目录，保留 components/pilot 文件夹结构。\n卸载组件：关闭飞行员后删除该文件夹。已保存的资料仍保留。')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

    def ground(self):
        self.mode = 'ground'
        self.accept()

    def pilot(self):
        command, status = pilot_component()
        if not command:
            self.status.setText(status)
            self.pilot_button.setEnabled(False)
            return
        ok, _ = QProcess.startDetached(command[0], command[1:])
        if ok:
            self.mode = 'pilot'
            self.accept()
        else:
            QMessageBox.warning(self, '飞行员组件无法启动', '请重新完整解压组件包。你仍可选择地面导航。')
