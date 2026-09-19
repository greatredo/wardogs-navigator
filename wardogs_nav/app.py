from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict,replace
from pathlib import Path
import json
import math
import time
import numpy as np
from PySide6.QtCore import Qt, QTimer, QLocale
from PySide6.QtGui import QImage, QPixmap, QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QLabel,
    QPushButton,QTabWidget,QScrollArea,QFormLayout,QCheckBox,QComboBox,QLineEdit,QListWidget,
    QGroupBox,QFileDialog,QMessageBox,QInputDialog,QDialog,QSplitter,QFrame)
from PySide6.QtTextToSpeech import QTextToSpeech
from .model import (asset_path,user_dir,atomic_json,default_settings,load_settings,read_project,
                    validate_project,upgrade_road_data,uid,KINDS,NOTE_TYPES)
from .vision import Fix
from . import __version__
from .routing import plan,RouteError,distance,bearing,nearest_on_route
from .navigation import Navigator, cues_for, cue_text, distance_text
from .library import saved_route,supplement_roads,follow_saved,library_payload,merge_library,snap_saved,check_library_target
from .maps import all_maps,map_info,map_asset,project_path,load_map_project
from .mapview import MapView
from .hud import Hud
from .dialogs import RoadDialog,NoteDialog,RegionDialog,FavoriteImportDialog,number
from .worker import CaptureWorker
from .overlay import MinimapOverlay,keep_on_top

STYLE='''
QWidget { background:#151d25; color:#e5ecee; font:10pt "Microsoft YaHei UI"; }
QMainWindow { background:#10171e; }
QLabel { background:transparent; }
QLabel#title { font:700 21pt "Segoe UI"; letter-spacing:2px; }
QLabel#muted { color:#93a6af; font-size:9pt; }
QLabel#banner { background:#22352f; color:#bfead9; padding:10px; border:1px solid #365148; border-radius:7px; }
QPushButton { background:#25313d; border:1px solid #3a4b58; border-radius:6px; padding:7px 10px; }
QPushButton:hover { background:#344958; border-color:#78938f; }
QPushButton:pressed { background:#1b2d35; }
QPushButton:disabled { color:#64757d; border-color:#2b3740; }
QPushButton#primary { background:#62ddba; color:#10281f; font-weight:700; border:0; padding:10px; }
QPushButton#primary:hover { background:#8ef0d3; }
QPushButton#selected { background:#456959; }
QTabWidget::pane { border:0; }
QTabBar::tab { background:#151d25; color:#96a8b1; padding:10px 18px; border-bottom:2px solid #253440; }
QTabBar::tab:selected { color:#77e5c3; border-bottom:2px solid #77e5c3; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox { background:#10181f; border:1px solid #344550; border-radius:5px; padding:5px; min-height:22px; }
QComboBox::drop-down { border:0; width:22px; }
QCheckBox { spacing:8px; padding:4px 0; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #5b7380; border-radius:3px; background:#10181f; }
QCheckBox::indicator:checked { background:#61daba; border-color:#61daba; }
QGroupBox { border:1px solid #30404b; border-radius:7px; margin-top:16px; padding:14px 10px 10px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; color:#b4c6cf; }
QListWidget { background:#111a21; border:1px solid #30404b; border-radius:5px; padding:4px; }
QListWidget::item { padding:6px 4px; }
QListWidget::item:selected { background:#29483f; color:#96efd1; }
QScrollArea { border:0; }
QScrollBar:vertical { background:#16212a; width:9px; }
QScrollBar::handle:vertical { background:#41545e; border-radius:4px; min-height:25px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QToolTip { color:#e5ecee; background:#293943; border:1px solid #607b88; }
QStatusBar { background:#11191f; color:#9bb1bd; }
'''


class MainWindow(QMainWindow):
    def __init__(self, start_worker=True):
        super().__init__()
        screen=QApplication.primaryScreen().availableGeometry()
        self.resize(min(1400,int(screen.width()*.94)),min(900,int(screen.height()*.92)))
        self.setMinimumSize(1000,660)
        self.settings=load_settings()
        if self.settings['map_id'] not in {m['id'] for m in all_maps()}:self.settings['map_id']='ozeti'
        self.project=read_project(map_asset(self.settings['map_id'],'project'))
        self.load_error=None
        if project_path(self.settings['map_id']).exists():
            try:self.project=load_map_project(self.settings['map_id'])
            except (OSError,ValueError,KeyError,TypeError) as error:self.load_error=str(error)
        upgraded,changed=upgrade_road_data(self.project)
        if changed:
            backup=user_dir()/'project-before-map-v2.json'
            if not backup.exists():atomic_json(backup,self.project)
            self.project=upgraded
        self.history=[]
        self.route=None
        self.full_route=None
        self.fix=None
        self.fix_live=False
        self.fix_time=0.
        self.pending_start=False
        self.jump_candidate=None
        self.jump_count=0
        self.last_accepted=None
        self.last_accepted_time=0.
        self.frame=None
        self.frame_diagnostic=None
        self.failure_diagnostic=None
        self.favorite_trip=None
        self.draft_kinds=[]
        self.navigator=Navigator()
        self.calibration_points=[]
        self.worker=CaptureWorker(self.settings)
        self.worker.result.connect(self.on_fix)
        self.worker.ready.connect(self.worker_ready)
        self.worker.failed.connect(self.worker_error)
        self.tts=QTextToSpeech('sapi',self)
        self.tts.errorOccurred.connect(lambda *_:self.voice_status.setText('系统语音不可用，请检查 Windows 语音包'))
        self.voices=[]
        self.hud=Hud(self.settings['hud'])
        self.minimap_overlay=MinimapOverlay(self.settings['minimap_overlay'])
        self.minimap_overlay.mask_changed.connect(lambda mask:setattr(self.worker,'path_mask',mask))
        self.hud.changed.connect(self.save_settings)
        self.build_ui()
        self.setWindowTitle('WARDOGS Navigator '+__version__+' · '+map_info(self.project['map'])['name'])
        self.setWindowFlag(Qt.WindowStaysOnTopHint,self.settings['main_topmost'])
        self.refresh_lists()
        self.refresh_map()
        self.autosave=QTimer(self);self.autosave.setSingleShot(True);self.autosave.setInterval(500);self.autosave.timeout.connect(self.save_project)
        self.watchdog=QTimer(self);self.watchdog.timeout.connect(self.check_stale);self.watchdog.start(500)
        QTimer.singleShot(700,self.load_voices)
        if start_worker:self.worker.start()
        QTimer.singleShot(0,self.map.fit)
        if self.load_error:QTimer.singleShot(300,lambda:self.notify('上次配置读取失败，已载入内置路网；原文件保留。'+self.load_error))
        elif changed:QTimer.singleShot(300,lambda:self.notify('已升级干净底图与道路数据；目的地、危险区及自定义内容已保留，旧配置已备份。'))
        elif self.project['map']=='ozeti' and self.project.get('road_data_revision',1)<2:QTimer.singleShot(300,lambda:self.notify('已保留你编辑过的道路；可在“地图标注”中载入新版道路数据。'))
        QShortcut(QKeySequence('Ctrl+Z'),self,self.undo)
        QShortcut(QKeySequence('Escape'),self,self.cancel_tool)
        QShortcut(QKeySequence('Return'),self,self.finish_road)
        QShortcut(QKeySequence('Ctrl+S'),self,self.save_project)
        QShortcut(QKeySequence('Backspace'),self,self.undo_draw_point)

    def button(self,text,callback,primary=False):
        b=QPushButton(text);b.clicked.connect(callback)
        if primary:b.setObjectName('primary')
        return b

    def row(self,*widgets):
        box=QWidget();layout=QHBoxLayout(box);layout.setContentsMargins(0,0,0,0);layout.setSpacing(6)
        for widget in widgets:layout.addWidget(widget)
        return box

    def text(self,text,muted=False):
        label=QLabel(text);label.setWordWrap(True)
        if muted:label.setObjectName('muted')
        return label

    def group(self,title,parent):
        box=QGroupBox(title);layout=QVBoxLayout(box);layout.setSpacing(8);parent.addWidget(box);return layout

    def page(self,title):
        widget=QWidget();layout=QVBoxLayout(widget);layout.setContentsMargins(6,9,10,12);layout.setSpacing(8)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(widget);self.tabs.addTab(scroll,title);return layout

    def build_ui(self):
        self.clear_waypoint_buttons=[];self.clear_avoid_buttons=[]
        central=QWidget();self.setCentralWidget(central);outer=QVBoxLayout(central);outer.setContentsMargins(18,14,18,10);outer.setSpacing(12)
        header=QHBoxLayout();title=QLabel('WARDOGS');title.setObjectName('title');header.addWidget(title)
        header.addWidget(self.text('地面载具导航',True))
        self.map_combo=QComboBox();self.map_combo.setMinimumWidth(155)
        for info in all_maps():self.map_combo.addItem(info['name'],info['id'])
        self.map_combo.setCurrentIndex(self.map_combo.findData(self.project['map']))
        self.map_combo.setToolTip('切换地图；道路、收藏、路书与危险区按地图独立保存')
        self.map_combo.currentIndexChanged.connect(self.choose_map);header.addWidget(self.map_combo);header.addStretch()
        for label,callback in [('撤销',self.undo),('导入配置',self.import_project),('导出配置',self.export_project),('使用说明',self.help)]:header.addWidget(self.button(label,callback))
        outer.addLayout(header)
        self.banner=self.text('① 框选小地图并开启定位   ② 点选目的地与途经点   ③ 开始导航');self.banner.setObjectName('banner');outer.addWidget(self.banner)
        splitter=QSplitter();outer.addWidget(splitter,1)
        self.tabs=QTabWidget();self.tabs.setMinimumWidth(350);self.tabs.setMaximumWidth(475);splitter.addWidget(self.tabs)
        right=QWidget();right_layout=QVBoxLayout(right);right_layout.setContentsMargins(8,0,0,0)
        toolbar_box=QWidget();toolbar_box.setStyleSheet('QPushButton { padding:7px 4px; }')
        toolbar_layout=QVBoxLayout(toolbar_box);toolbar_layout.setContentsMargins(0,0,0,0);toolbar_layout.setSpacing(6)
        toolbar=QHBoxLayout();toolbar_layout.addLayout(toolbar)
        for label,tool in [('移动 / 选路','pan'),('起始点','start'),('目的地','destination'),('危险区','avoid'),('途经点','waypoint'),('绘制道路','road')]:toolbar.addWidget(self.button(label,lambda _,t=tool:self.set_tool(t)))
        toolbar.addStretch();toolbar.addWidget(self.button('适应地图',lambda:self.map.fit()));right_layout.addWidget(toolbar_box)
        cleanup=QHBoxLayout();toolbar_layout.addLayout(cleanup)
        cleanup.addWidget(self.clear_route_button('toolbar'))
        cleanup.addWidget(self.clear_button('waypoints','toolbar'));cleanup.addWidget(self.clear_button('avoid','toolbar'));cleanup.addStretch()
        self.draw_kind=QComboBox()
        for key,label in KINDS.items():self.draw_kind.addItem(label,key)
        self.draw_kind.setCurrentIndex(1)
        self.draw_snap=QCheckBox('吸附道路');self.draw_snap.setChecked(True)
        self.draw_kind_label=QLabel('道路 / 下一段类型')
        self.drawing_bar=self.row(self.draw_kind_label,self.draw_kind,self.draw_snap,
                                  self.button('退一点',self.undo_draw_point),self.button('完成',self.finish_road),self.button('取消',self.cancel_tool))
        self.drawing_bar.hide();right_layout.addWidget(self.drawing_bar)
        self.favorite_snap=QCheckBox('贴合现有道路')
        self.favorite_build=QCheckBox('按路径建立缺失道路');self.favorite_build.setChecked(True)
        self.favorite_options=self.row(self.favorite_snap,self.favorite_build)
        self.favorite_options.hide();right_layout.addWidget(self.favorite_options)
        self.favorite_preview_label=self.text('',True);self.favorite_preview_label.hide();right_layout.addWidget(self.favorite_preview_label)
        self.favorite_snap.toggled.connect(self.favorite_drawing_option)
        self.favorite_build.toggled.connect(self.favorite_drawing_option)
        self.draft_preview=None
        self.map=MapView(self.project['map']);right_layout.addWidget(self.map,1)
        self.map.clicked.connect(self.map_click);self.map.finished.connect(self.finish_road);self.map.moved.connect(self.move_item);self.map.remove_requested.connect(self.remove_item)
        self.map.region_selected.connect(self.add_danger_region)
        self.map.road_selected.connect(self.select_road_on_map)
        self.map.road_edit_requested.connect(self.edit_road_on_map)
        self.map.road_delete_requested.connect(self.delete_road_on_map)
        self.map.hover.connect(lambda x,y:self.coordinate_label.setText(f'地图坐标  {x:.0f}, {y:.0f}'))
        bottom=QHBoxLayout();legend=self.text('┄ 大路   ┄ 小路   ┄ 野地   ━ 导航路线',True);legend.setWordWrap(False);bottom.addWidget(legend);bottom.addStretch()
        self.coordinate_label=self.text('地图坐标 —',True);self.coordinate_label.setWordWrap(False);bottom.addWidget(self.coordinate_label);right_layout.addLayout(bottom)
        splitter.addWidget(right);splitter.setSizes([390,1050]);splitter.setStretchFactor(1,1)
        self.build_navigation();self.build_editor();self.build_library();self.build_settings()
        self.statusBar().showMessage('初始化视觉定位…')

    def build_navigation(self):
        layout=self.page('导航')
        status=self.group('定位',layout)
        self.fix_label=self.text('尚未定位');self.fix_label.setStyleSheet('font-size:15pt;color:#75e5c3;');status.addWidget(self.fix_label)
        self.fix_detail=self.text('小地图固定北朝上；在设置中检查截取预览。',True);status.addWidget(self.fix_detail)
        self.capture_button=self.button('开启定位',self.toggle_capture)
        status.addWidget(self.row(self.button('框选小地图',self.select_region),self.capture_button))
        self.start_button=self.button('开始导航',self.start_navigation,True);status.addWidget(self.start_button)
        status.addWidget(self.row(self.button('停止',self.stop_navigation),self.button('显示图标',self.show_hud),self.button('隐藏图标',self.hud.hide)))
        target=self.group('起始点、目的地与途经点',layout)
        target.addWidget(self.clear_route_button('navigation'))
        target.addWidget(self.row(self.clear_button('waypoints','navigation'),self.clear_button('avoid','navigation')))
        self.start_label=self.text('');target.addWidget(self.start_label)
        self.set_start_button=self.button('地图设置起点',lambda:self.set_tool('start'))
        self.current_start_button=self.button('使用当前位置',self.use_current_start)
        target.addWidget(self.row(self.set_start_button,self.current_start_button))
        target.addWidget(self.text('起始点也是返程终点，途中可修改；未设置时，开始导航会自动放在当前位置。',True))
        self.destination_label=self.text('在地图点选目的地');target.addWidget(self.destination_label)
        self.saved_dest=QComboBox();self.saved_dest.currentIndexChanged.connect(self.choose_destination);target.addWidget(self.saved_dest)
        target.addWidget(self.row(self.button('地图选点',lambda:self.set_tool('destination')),self.button('收藏目的地',self.save_destination)))
        self.waypoint_list=QListWidget();self.waypoint_list.setMaximumHeight(90);target.addWidget(self.waypoint_list)
        target.addWidget(self.row(self.button('添加途经点',lambda:self.set_tool('waypoint')),self.button('删除选中',self.delete_waypoint),self.button('框选危险区',lambda:self.set_tool('avoid'))))
        target.addWidget(self.text('拖框标记危险区域即可绕行；绿点用于指定必经位置。右键可删除标注。',True))
        self.roundtrip=QCheckBox('连续往返（到达后自动切换去程 / 返程）');self.roundtrip.setChecked(self.project['roundtrip']);self.roundtrip.toggled.connect(self.change_policy);target.addWidget(self.roundtrip)
        rules=self.group('路线规则',layout);self.kind_checks={}
        for key,label in KINDS.items():
            check=QCheckBox('允许'+label);check.setChecked(key in self.project['policy']['allowed']);check.toggled.connect(self.change_policy);self.kind_checks[key]=check;rules.addWidget(check)
        rules.addWidget(self.text('野地/越野默认关闭；地图无法判断地雷或实时障碍。',True))
        controls=self.group('导航与播报',layout)
        self.mode=QComboBox();self.mode.addItem('常规导航','normal');self.mode.addItem('WRC 路书','wrc');self.mode.setCurrentIndex(self.mode.findData(self.settings['mode']));self.mode.currentIndexChanged.connect(self.change_mode);controls.addWidget(self.mode)
        self.route_label=self.text('路线尚未规划',True);controls.addWidget(self.route_label)
        controls.addWidget(self.button('预览路线',self.preview_route))
        controls.addWidget(self.row(self.button('收藏当前路线',self.save_current_route),self.button('查看播报',self.preview_cues)))
        layout.addStretch()

    def build_editor(self):
        layout=self.page('地图标注')
        roads=self.group('道路',layout)
        self.roads_visible=QCheckBox('显示道路');self.roads_visible.setChecked(True);self.roads_visible.toggled.connect(self.toggle_roads);roads.addWidget(self.roads_visible)
        self.road_list=QListWidget();self.road_list.setMinimumHeight(180);self.road_list.currentRowChanged.connect(self.select_road);self.road_list.itemDoubleClicked.connect(lambda _:self.edit_road());roads.addWidget(self.road_list)
        roads.addWidget(self.row(self.button('绘制道路',lambda:self.set_tool('road')),self.button('完成绘制',self.finish_road)))
        roads.addWidget(self.row(self.button('编辑属性',self.edit_road),self.button('删除道路',self.delete_road)))
        roads.addWidget(self.row(self.button('导入路网',lambda:self.import_library('roads')),self.button('导出路网',lambda:self.export_library('roads'))))
        roads.addWidget(self.button('载入内置路网',self.reload_roads))
        roads.addWidget(self.text('“移动 / 选路”中单击道路选中并拖点，双击编辑属性，右键可编辑或删除；也可从列表选择。绘制时 Enter / 双击结束，相交处需要显式节点。',True))
        notes=self.group('WRC 路书',layout)
        self.note_list=QListWidget();self.note_list.setMaximumHeight(140);self.note_list.itemDoubleClicked.connect(lambda _:self.edit_note());notes.addWidget(self.note_list)
        notes.addWidget(self.row(self.button('地图添加',lambda:self.set_tool('note')),self.button('编辑',self.edit_note),self.button('删除',self.delete_note)))
        notes.addWidget(self.text('手动标注优先于估算弯级。导出配置包含道路、路书、避让区、目的地和路线规则。',True))
        avoids=self.group('避让区域',layout)
        self.avoid_list=QListWidget();self.avoid_list.setMaximumHeight(100);avoids.addWidget(self.avoid_list)
        avoids.addWidget(self.row(self.button('框选危险区',lambda:self.set_tool('avoid')),self.button('调整尺寸',self.edit_avoid),self.button('删除',self.delete_avoid)))
        avoids.addWidget(self.text('拖动区域中心移动，拖动右下角调整大小；红色区域内的道路禁止通行。',True))
        layout.addStretch()

    def build_library(self):
        layout=self.page('路线收藏')
        layout.addWidget(self.text('收藏完整走法',False))
        layout.addWidget(self.text('保存完整路线，或绘制收藏时勾选“贴合现有道路”，粗略放点即可沿道路规划。关闭贴合可保留原走法，并选择是否建立公共道路。危险区会触发局部绕行。',True))
        self.favorite_list=QListWidget();self.favorite_list.setMinimumHeight(180)
        self.favorite_list.itemDoubleClicked.connect(lambda _:self.load_favorite());layout.addWidget(self.favorite_list)
        self.favorite_status=self.text('当前使用自动规划',True);layout.addWidget(self.favorite_status)
        layout.addWidget(self.row(self.button('载入',self.load_favorite),self.button('反向载入',lambda:self.load_favorite(reverse=True))))
        layout.addWidget(self.row(self.button('收藏当前路线',self.save_current_route),self.button('绘制收藏路径',lambda:self.set_tool('favorite'))))
        layout.addWidget(self.row(self.button('重命名',self.rename_favorite),self.button('删除收藏',self.delete_favorite)))
        layout.addWidget(self.row(self.button('导入收藏',lambda:self.import_library('routes')),self.button('导出收藏',lambda:self.export_library('routes'))))
        layout.addWidget(self.button('退出收藏，恢复自动规划',self.clear_favorite))
        layout.addWidget(self.text('不贴路时可切换下一段类型。不建路的收藏仍可导航，只在该收藏中使用缺路部分。导入时确认贴路/建路选项；导出保留完整路径、类型、粗绘点、选项和路书。顶部“配置”备份全部内容。',True))
        layout.addStretch()

    def build_settings(self):
        layout=self.page('设置')
        capture=self.group('屏幕识别区域',layout)
        self.screen_combo=QComboBox();self.monitors=[]
        try:
            import mss
            with mss.MSS() as sct:self.monitors=[dict(m) for m in sct.monitors[1:]]
        except Exception:pass
        for i,m in enumerate(self.monitors):self.screen_combo.addItem(f"显示器 {i+1} · {m['width']} × {m['height']}")
        capture.addWidget(self.screen_combo)
        capture.addWidget(self.button('框选此屏幕的小地图',self.select_region))
        form=QFormLayout();self.capture_fields={}
        for key,label,lo,hi in [('left','左边 X',-30000,30000),('top','上边 Y',-30000,30000),('width','宽度',60,5000),('height','高度',60,5000)]:
            w=number(self.settings['capture'][key],lo,hi);w.valueChanged.connect(lambda value,k=key:self.capture_setting(k,value));self.capture_fields[key]=w;form.addRow(label,w)
        self.anchor_x=number(self.settings['anchor'][0]*100,0,100,1);self.anchor_y=number(self.settings['anchor'][1]*100,0,100,1)
        self.anchor_x.valueChanged.connect(self.anchor_setting);self.anchor_y.valueChanged.connect(self.anchor_setting)
        form.addRow('玩家锚点 X (%)',self.anchor_x);form.addRow('玩家锚点 Y (%)',self.anchor_y)
        self.interval=number(self.settings['interval_ms'],200,3000);self.interval.valueChanged.connect(lambda v:self.set_setting('interval_ms',v));form.addRow('识别间隔 (ms)',self.interval);capture.addLayout(form)
        self.north_up=QCheckBox('小地图固定北朝上');self.north_up.setChecked(self.settings['north_up']);self.north_up.toggled.connect(lambda v:self.set_setting('north_up',v));capture.addWidget(self.north_up)
        self.preview=QLabel('定位时显示截取预览');self.preview.setAlignment(Qt.AlignCenter);self.preview.setMinimumHeight(140);capture.addWidget(self.preview)
        capture.addWidget(self.button('用图片检验定位',self.test_image))
        capture.addWidget(self.button('保存定位诊断',self.save_capture_diagnostic))
        overlay=self.group('置顶与小地图路径',layout)
        topmost=QCheckBox('主窗口置顶');topmost.setChecked(self.settings['main_topmost']);topmost.toggled.connect(self.set_main_topmost);overlay.addWidget(topmost)
        self.overlay_check=QCheckBox('在游戏小地图上叠加路径');self.overlay_check.setChecked(self.settings['minimap_overlay']['enabled']);self.overlay_check.toggled.connect(lambda v:self.overlay_setting('enabled',v));overlay.addWidget(self.overlay_check)
        of=QFormLayout()
        for key,label,lo,hi,dec in [('opacity','路径不透明度',.2,1,2),('line_width','路径线宽 (屏幕像素)',1,10,0)]:
            w=number(self.settings['minimap_overlay'][key],lo,hi,dec);w.valueChanged.connect(lambda v,k=key:self.overlay_setting(k,v));of.addRow(label,w)
        overlay.addLayout(of)
        self.overlay_status=self.text('实时导航时显示；自动跟随截图区域、缩放及旋转。路径窗口不接收鼠标输入。',True);overlay.addWidget(self.overlay_status)
        speech=self.group('语音与提前量',layout)
        self.voice_check=QCheckBox('启用离线语音');self.voice_check.setChecked(self.settings['voice']);self.voice_check.toggled.connect(self.change_voice);speech.addWidget(self.voice_check)
        self.voice_combo=QComboBox();self.voice_combo.currentIndexChanged.connect(self.select_voice);speech.addWidget(self.voice_combo)
        self.voice_status=self.text('读取系统语音…',True);speech.addWidget(self.voice_status)
        sf=QFormLayout()
        for key,label,lo,hi,decimals in [('lead_m','常规提前距离 (m)',0,1500,0),('lead_s','常规车速提前 (s)',0,20,1),('wrc_lead_m','WRC 提前距离 (m)',0,1500,0),('wrc_lead_s','WRC 车速提前 (s)',0,20,1),('wrc_chain_m','WRC 连读间隔 (m)',0,300,0),('arrival_m','到达半径 (m)',5,100,0),('offroute_m','偏航重算阈值 (m)',20,500,0),('voice_rate','语速 (-1 慢 / 1 快)',-1,1,1)]:
            w=number(self.settings[key],lo,hi,decimals);w.valueChanged.connect(lambda value,k=key:self.set_setting(k,value));sf.addRow(label,w)
        speech.addLayout(sf);speech.addWidget(self.button('试听当前模式',self.test_voice))
        hud=self.group('导航图标',layout);hf=QFormLayout();self.hud_fields={}
        for key,label,lo,hi,decimals in [('x','屏幕 X',-30000,30000,0),('y','屏幕 Y',-30000,30000,0),('width','宽度',240,1200,0),('height','高度',110,600,0),('opacity','不透明度',.2,1,2)]:
            w=number(self.settings['hud'][key],lo,hi,decimals);w.valueChanged.connect(lambda value,k=key:self.hud_setting(k,value));self.hud_fields[key]=w;hf.addRow(label,w)
        hud.addLayout(hf)
        self.hud_lock=QCheckBox('锁定并启用鼠标穿透');self.hud_lock.setChecked(self.settings['hud']['locked']);self.hud_lock.toggled.connect(lambda v:self.hud_setting('locked',v));hud.addWidget(self.hud_lock)
        hud.addWidget(self.row(self.button('显示 / 预览',self.show_hud),self.button('移回主屏',self.reset_hud)))
        hud.addWidget(self.text('优先保留游戏全屏模式，叠加层保持置顶。显示效果取决于 Windows 全屏优化；真正独占全屏可能遮挡。位置、尺寸按 Windows 逻辑像素。',True))
        scale=self.group('距离校准',layout);self.scale_label=self.text('');scale.addWidget(self.scale_label);self.update_scale_label()
        scale.addWidget(self.row(self.button('地图两点校准',lambda:self.set_tool('calibrate')),self.button('输入米/像素',self.set_scale)))
        layout.addStretch()

    def notify(self,text):
        self.banner.setText(text)
        self.statusBar().showMessage(text,10000)

    def choose_map(self,index):
        map_id=self.map_combo.itemData(index)
        if map_id and map_id!=self.project['map']:
            if not self.switch_map(map_id):
                self.map_combo.blockSignals(True);self.map_combo.setCurrentIndex(self.map_combo.findData(self.project['map']));self.map_combo.blockSignals(False)

    def switch_map(self,map_id):
        if map_id==self.project['map']:return True
        try:
            target=load_map_project(map_id)
            if QPixmap(str(map_asset(map_id,'image'))).isNull() or not map_asset(map_id,'features').is_file():
                raise ValueError('此地图资源缺失，请完整解压便携包')
        except (OSError,ValueError,TypeError,KeyError) as error:
            self.notify(f'未切换地图：{error}');return False
        self.autosave.stop()
        if not self.save_project():return False
        self.stop_navigation(quiet=True);self.worker.capture=False;self.capture_button.setText('开启定位')
        self.worker.request_map(map_id)
        self.settings['map_id']=map_id;self.project=target;self.history=[]
        self.route=None;self.full_route=None;self.favorite_trip=None;self.frame=None
        self.frame_diagnostic=None;self.failure_diagnostic=None
        self.fix=None;self.fix_live=False;self.fix_time=0.;self.pending_start=False
        self.last_accepted=None;self.last_accepted_time=0.;self.jump_candidate=None;self.jump_count=0
        self.navigator=Navigator();self.calibration_points=[];self.draft_kinds=[]
        self.map.project=target;self.map.load_map(map_id);self.drawing_bar.hide();self.favorite_options.hide();self.favorite_preview_label.hide();self.draft_preview=None
        self.map_combo.blockSignals(True);self.map_combo.setCurrentIndex(self.map_combo.findData(map_id));self.map_combo.blockSignals(False)
        self.sync_policy();self.refresh_lists();self.refresh_map();self.update_scale_label()
        self.preview.clear();self.preview.setText('开启定位后显示当前地图的小地图预览')
        self.fix_label.setText('尚未定位');self.fix_detail.setText('已切换地图，正在准备对应的定位特征。')
        self.route_label.setText('路线尚未规划');self.coordinate_label.setText('地图坐标 —')
        name=map_info(map_id)['name'];self.setWindowTitle('WARDOGS Navigator '+__version__+' · '+name)
        self.save_settings();self.notify(f'已切换到 {name}；道路、收藏和路书已载入。开启定位后重新开始导航。')
        return True

    def worker_ready(self,map_id,generation):
        if (map_id,generation)!=self.worker.context or map_id!=self.project['map']:return
        self.fix_detail.setText('小地图固定北朝上；在设置中检查截取预览。')
        self.statusBar().showMessage(map_info(map_id)['name']+' 视觉定位已就绪 · 请开启定位')

    def reload_roads(self):
        if QMessageBox.question(self,'载入道路数据','替换当前道路为内置路网？目的地、危险区和路书保留。当前完整配置会先备份；可用撤销恢复。')!=QMessageBox.Yes:return
        atomic_json(user_dir()/f'project-before-road-reload-{time.time_ns()}.json',self.project)
        self.snapshot();latest=read_project(map_asset(self.project['map'],'project'))
        self.project['roads']=latest['roads'];self.project['road_data_revision']=latest['road_data_revision'];self.changed();self.notify('内置道路已载入；原配置已备份')

    def snapshot(self):
        self.history.append(deepcopy(self.project));self.history=self.history[-30:]

    def changed(self,replan=True):
        resume=self.navigator.active and self.fix_live and self.fix and self.fix.valid
        leg,lap=self.navigator.leg,self.navigator.lap
        anchors=None
        if resume:
            waypoints=list(self.project['waypoints'])
            if lap%2:waypoints.reverse()
            remaining=[]
            for p in waypoints:
                q=nearest_on_route(p,self.navigator.route.points)
                if q is None or q[0]>25 or q[1]>self.navigator.progress+3:remaining.append(p)
            goal=self.project['start'] if lap%2 else self.project['destination']
            if goal:anchors=[[self.fix.x,self.fix.y],*remaining,goal]
        self.stop_navigation(quiet=True)
        self.pending_start=False
        self.route=None;self.full_route=None;self.map.route=None
        self.refresh_lists();self.refresh_map();self.autosave.start()
        if replan and self.project['destination'] and (self.project['start'] or (self.fix and self.fix.valid) or self.active_favorite()):
            success=self.plan_route(quiet=True,anchors=anchors)
            if resume and success:
                self.navigator.start(self.route,self.project['notes'],self.settings,self.project['meters_per_pixel'],self.project['roundtrip'])
                self.navigator.leg,self.navigator.lap=leg,lap
                self.update_minimap_overlay()
                self.speak('路线已更新')

    def save_project(self):
        try:atomic_json(project_path(self.project['map']),validate_project(self.project));return True
        except (OSError,ValueError,TypeError) as error:self.notify(f'保存失败：{error}');return False

    def save_settings(self):
        try:atomic_json(user_dir()/'settings.json',self.settings)
        except (OSError,ValueError) as error:self.notify(f'设置保存失败：{error}')

    def refresh_lists(self):
        self.road_list.blockSignals(True);selected=self.map.selected_road;self.road_list.clear()
        for r in self.project['roads']:self.road_list.addItem(f"{r['name']}  /  {KINDS[r['kind']]}")
        self.road_list.setCurrentRow(next((i for i,r in enumerate(self.project['roads']) if r['id']==selected),-1));self.road_list.blockSignals(False)
        self.note_list.clear()
        for n in self.project['notes']:self.note_list.addItem(f"{NOTE_TYPES[n['type']]} {n['grade'] if n['type'] in ('left','right') else ''} · {n.get('text') or '标准播报'}")
        self.avoid_list.clear()
        for i,z in enumerate(self.project['avoid']):
            scale=self.project['meters_per_pixel'] or 1
            size=f"{z['width']*scale:.0f} × {z['height']*scale:.0f}" if z.get('shape')=='rect' else f"半径 {z['radius']*scale:.0f}"
            self.avoid_list.addItem(f"危险区 {i+1} · {size} {'m' if self.project['meters_per_pixel'] else '单位'}")
        self.waypoint_list.clear()
        for i,p in enumerate(self.project['waypoints']):self.waypoint_list.addItem(f'{i+1:02}  途经 {p[0]:.0f}, {p[1]:.0f}')
        self.waypoint_list.setVisible(bool(self.project['waypoints']))
        for button in self.clear_waypoint_buttons:button.setEnabled(bool(self.project['waypoints']))
        for button in self.clear_avoid_buttons:button.setEnabled(bool(self.project['avoid']))
        self.saved_dest.blockSignals(True);self.saved_dest.clear();self.saved_dest.addItem('选择收藏的目的地')
        for d in self.project['destinations']:self.saved_dest.addItem(d['name'])
        self.saved_dest.blockSignals(False)
        start=self.project['start']
        self.start_label.setText(f'起始点 / 返程终点  {start[0]:.0f}, {start[1]:.0f}' if start else '起始点未设置 · 开始导航时使用当前位置')
        d=self.project['destination'];label='去程终点' if self.project['roundtrip'] else '终点'
        self.destination_label.setText(f'{label}  {d[0]:.0f}, {d[1]:.0f}' if d else '在地图点选目的地')
        selected=self.favorite_list.currentRow();self.favorite_list.clear()
        for saved in self.project['route_library']:
            active='▶ ' if saved['id']==self.project.get('active_route_id') else ''
            self.favorite_list.addItem(active+saved['name'])
        if selected>=0:self.favorite_list.setCurrentRow(min(selected,self.favorite_list.count()-1))
        active=self.active_favorite()
        self.favorite_status.setText(('当前收藏：'+active['name']+(' · 反向' if self.project.get('active_route_reverse') else '')) if active else '当前使用自动规划')

    def refresh_map(self):
        self.update_favorite_preview()
        self.map.project=self.project;self.map.route=self.route;self.map.full_route=self.full_route;self.map.fix=self.fix;self.map.redraw()

    def favorite_drawing_option(self,*_):
        self.update_drawing_controls()
        self.refresh_map()

    def update_drawing_controls(self):
        follow=self.map.tool=='favorite' and self.favorite_snap.isChecked()
        self.favorite_build.setVisible(not self.favorite_snap.isChecked())
        for widget in (self.draw_kind_label,self.draw_kind,self.draw_snap):
            widget.setVisible(not follow);widget.setEnabled(not follow)

    def update_favorite_preview(self):
        self.draft_preview=None;self.map.draft_path=[]
        if self.map.tool!='favorite':return
        if not self.favorite_snap.isChecked():
            self.favorite_preview_label.setText('保留绘制的完整路径；'+('缺失部分将补入公共路网。' if self.favorite_build.isChecked() else '仅用于本收藏导航，不建立公共道路。'))
            return
        if len(self.map.draft)<2:
            self.favorite_preview_label.setText('粗略点选起点、沿途控制点与终点；绿色预览线会沿当前允许的道路行驶。')
            return
        try:
            raw=dict(id='preview',name='绘制预览',points=self.map.draft,kinds=self.draft_kinds,control_points=self.map.draft)
            self.draft_preview=snap_saved(self.project['roads'],raw,self.project['policy'],self.project['avoid'])
            points=self.draft_preview['points'];self.map.draft_path=points
            length=sum(distance(a,b) for a,b in zip(points,points[1:]))*(self.project['meters_per_pixel'] or 1)
            unit='米' if self.project['meters_per_pixel'] else '地图单位'
            self.favorite_preview_label.setText(f'贴路预览 · {length:.0f} {unit} · {len(self.map.draft)} 个粗绘点；Enter 保存完整路径，不新增公共道路。')
        except RouteError as error:self.favorite_preview_label.setText(str(error)+'；可退一点或调整道路规则。')

    def set_tool(self,tool):
        if self.map.tool!=tool:
            self.map.draft=[];self.draft_kinds=[]
        self.map.set_tool(tool)
        self.drawing_bar.setVisible(tool in ('road','favorite'))
        self.favorite_options.setVisible(tool=='favorite');self.favorite_preview_label.setVisible(tool=='favorite')
        self.update_drawing_controls()
        tips={'pan':'拖动平移，滚轮缩放；单击选路并拖点，双击改属性，右键可删除','destination':'在地图单击设置目的地（退出收藏路线）','waypoint':'单击增加途经点；顺序为路线必经顺序（退出收藏路线）','avoid':'按住鼠标拖出矩形危险区，松开后自动绕行','road':'选择类型，沿道路或野地逐点绘制；Enter / 双击完成，Backspace 退一点','favorite':'逐点绘制完整路径；可勾选贴合道路，或选择是否建立缺失道路；Enter 保存','note':'在路线旁单击添加 WRC 路书','calibrate':'依次点选两个已知距离的地标'}
        tips['start']='在地图单击设置起始点；往返时此点为返程终点，可随时拖动修改'
        self.notify(tips[tool])
        if tool=='calibrate':self.calibration_points=[]
        self.refresh_map()

    def cancel_tool(self):
        self.map.draft=[];self.draft_kinds=[];self.calibration_points=[];self.map.selected_road=None;self.set_tool('pan');self.refresh_map()

    def undo_draw_point(self):
        if self.map.tool in ('road','favorite') and self.map.draft:
            self.map.draft.pop()
            if self.draft_kinds:self.draft_kinds.pop()
            self.refresh_map()

    def active_favorite(self):
        return next((r for r in self.project['route_library'] if r['id']==self.project.get('active_route_id')),None)

    def detach_favorite(self):
        self.project.pop('active_route_id',None);self.project.pop('active_route_reverse',None);self.favorite_trip=None

    def clear_favorite(self):
        self.snapshot();self.detach_favorite();self.changed();self.notify('已恢复目的地与途经点自动规划')

    def map_click(self,x,y):
        p=[x,y];tool=self.map.tool
        if tool=='start':self.set_start(p);self.set_tool('pan')
        elif tool=='destination':self.snapshot();self.detach_favorite();self.project['destination']=p;self.changed();self.set_tool('pan')
        elif tool=='waypoint':self.snapshot();self.detach_favorite();self.project['waypoints'].append(p);self.changed()
        elif tool=='avoid':
            radius,ok=QInputDialog.getInt(self,'避让区域','半径（米）',150,10,3000,10)
            if ok:self.snapshot();self.project['avoid'].append({'point':p,'radius':radius/(self.project['meters_per_pixel'] or 1)});self.changed();self.set_tool('pan')
        elif tool in ('road','favorite'):
            # Snap to existing segment: a vertex explicitly added here joins it.
            from .routing import project
            options=[project(p,a,b) for r in self.project['roads'] for a,b in zip(r['points'],r['points'][1:])]
            if options and self.draw_snap.isChecked() and not(tool=='favorite' and self.favorite_snap.isChecked()):
                best=min(options,key=lambda q:q[0])
                if best[0]<8:p=list(best[1])
            if not self.map.draft or distance(p,self.map.draft[-1])>1:
                if self.map.draft:self.draft_kinds.append(self.draw_kind.currentData())
                self.map.draft.append(p)
            self.refresh_map()
        elif tool=='note':
            dialog=NoteDialog(parent=self)
            if self.route:
                projection=nearest_on_route(p,self.route.points)
                if projection:
                    _,_,i,_=projection;dialog.bearing.setValue(round(bearing(self.route.points[i],self.route.points[i+1])))
            if dialog.exec()==QDialog.Accepted:
                self.snapshot();self.project['notes'].append(dict(id=uid(),point=p,**dialog.values()));self.changed();self.set_tool('pan')
        elif tool=='calibrate':
            self.calibration_points.append(p);self.map.draft=list(self.calibration_points);self.refresh_map()
            if len(self.calibration_points)==2:
                length=distance(*self.calibration_points)
                if length<5:self.notify('两点过近，请重新校准');self.cancel_tool();return
                meters,ok=QInputDialog.getDouble(self,'距离校准','两点的游戏内距离（米）',1000,1,30000,1)
                if ok:
                    self.snapshot();self.project['meters_per_pixel']=meters/length;self.project['calibration']={'source':'用户两点距离校准','points':self.calibration_points,'distance_m':meters,'status':'用户校准'};self.changed();self.update_scale_label()
                self.cancel_tool()

    def finish_road(self):
        if self.map.tool=='favorite':self.finish_favorite();return
        if self.map.tool!='road' or len(self.map.draft)<2:return
        dialog=RoadDialog({'kind':self.draw_kind.currentData()},self)
        if dialog.exec()==QDialog.Accepted:
            self.snapshot();self.project['roads'].append(dict(id=uid(),points=deepcopy(self.map.draft),**dialog.values()));self.map.draft=[];self.changed();self.set_tool('pan')

    def finish_favorite(self):
        if len(self.map.draft)<2:return
        self.update_favorite_preview()
        if self.favorite_snap.isChecked() and self.draft_preview is None:
            self.notify(self.favorite_preview_label.text());return
        name,ok=QInputDialog.getText(self,'收藏完整路径','路线名称')
        if not ok or not name.strip():return
        saved=deepcopy(self.draft_preview) if self.favorite_snap.isChecked() else dict(points=deepcopy(self.map.draft),kinds=list(self.draft_kinds),snap_to_roads=False,build_roads=self.favorite_build.isChecked())
        saved.update(id=uid(),name=name.strip()[:200])
        if self.store_favorite(saved):self.cancel_tool()

    def store_favorite(self,saved):
        saved=deepcopy(saved);saved.setdefault('snap_to_roads',False);saved.setdefault('build_roads',True)
        candidate=deepcopy(self.project);candidate['route_library'].append(saved)
        count=supplement_roads(candidate['roads'],saved) if saved['build_roads'] else 0
        try:candidate=validate_project(candidate)
        except ValueError as error:self.notify('收藏未保存：'+str(error));return False
        self.snapshot();self.project=candidate;self.refresh_lists();self.refresh_map();self.autosave.start()
        self.favorite_list.setCurrentRow(len(self.project['route_library'])-1)
        detail=f'补入 {count} 条道路。' if saved['build_roads'] else '未新增公共道路。'
        self.notify('已收藏完整路径；'+detail+'可在“路线收藏”载入。')
        return True

    def save_current_route(self):
        if not self.route:self.notify('请先预览或规划一条路线');return
        name,ok=QInputDialog.getText(self,'收藏当前完整路线','路线名称')
        if ok and name.strip():
            route=self.route
            active=self.active_favorite() or {}
            self.store_favorite(saved_route(name.strip()[:200],route,snap_to_roads=active.get('snap_to_roads',False),build_roads=active.get('build_roads',True)))
            self.route=route;self.refresh_map()

    def load_favorite(self,reverse=False):
        i=self.favorite_list.currentRow()
        if i<0:self.notify('请先选择收藏路线');return
        saved=self.project['route_library'][i]
        self.snapshot();count=supplement_roads(self.project['roads'],saved) if saved.get('build_roads',True) else 0
        self.favorite_trip=None
        self.project['active_route_id']=saved['id'];self.project['active_route_reverse']=bool(reverse)
        self.project['start']=list(saved['points'][-1 if reverse else 0])
        self.project['destination']=list(saved['points'][0 if reverse else -1]);self.project['waypoints']=[]
        self.changed(replan=False)
        if self.plan_route(preview_full=True,quiet=True):
            detail=f'补入 {count} 条道路。' if saved.get('build_roads',True) else '仅用于本收藏，未建立公共道路。'
            self.notify(f"已载入 {saved['name']} 的完整路径与起终点；{detail}开始导航时接入当前位置，可另行修改起始点。")
        else:self.notify(self.route_label.text())

    def rename_favorite(self):
        i=self.favorite_list.currentRow()
        if i<0:return
        saved=self.project['route_library'][i]
        name,ok=QInputDialog.getText(self,'重命名收藏','名称',text=saved['name'])
        if ok and name.strip():self.snapshot();saved['name']=name.strip()[:200];self.refresh_lists();self.autosave.start()

    def delete_favorite(self):
        i=self.favorite_list.currentRow()
        if i<0:return
        self.snapshot();saved=self.project['route_library'].pop(i)
        if saved['id']==self.project.get('active_route_id'):self.detach_favorite()
        self.changed()

    def import_library(self,kind):
        label='路网' if kind=='roads' else '路线收藏'
        path,_=QFileDialog.getOpenFileName(self,'合并导入'+label,'','JSON (*.json)')
        if not path:return
        try:
            incoming=read_project(path);check_library_target(self.project,incoming,kind)
            options={}
            if kind=='routes':
                dialog=FavoriteImportDialog(incoming['route_library'],self)
                if dialog.exec()!=QDialog.Accepted:return
                options=dialog.options()
            data,count,supplemented=merge_library(self.project,incoming,kind,**options)
        except (OSError,ValueError,TypeError,KeyError) as error:self.notify(f'导入失败：{error}');return
        self.snapshot();self.project=data;self.changed()
        self.notify(f'已合并 {count} 项{label}，补入 {supplemented} 条道路；原有标注保留，可撤销')

    def export_library(self,kind):
        label='路网' if kind=='roads' else '路线收藏'
        path,_=QFileDialog.getSaveFileName(self,'导出'+label,map_info(self.project['map'])['name']+'-'+label+'.json','JSON (*.json)')
        if not path:return
        try:atomic_json(path,library_payload(self.project,kind));self.notify(label+'已导出：'+path)
        except (OSError,ValueError,TypeError) as error:self.notify(f'导出失败：{error}')

    def select_road(self,index):
        self.map.selected_road=self.project['roads'][index]['id'] if 0<=index<len(self.project['roads']) else None;self.refresh_map()

    def select_road_on_map(self,road_id):
        index=next((i for i,r in enumerate(self.project['roads']) if r['id']==road_id),-1)
        if self.map.tool!='pan':self.set_tool('pan')
        self.road_list.blockSignals(True);self.road_list.setCurrentRow(index);self.road_list.blockSignals(False)
        self.select_road(index)
        if index>=0:
            self.road_list.scrollToItem(self.road_list.item(index))
            self.notify('已选中 '+self.project['roads'][index]['name']+'；拖动节点修改，双击道路编辑属性，右键可删除。')

    def edit_road_on_map(self,road_id):
        self.select_road_on_map(road_id);self.edit_road()

    def delete_road_on_map(self,road_id):
        self.select_road_on_map(road_id);self.delete_road()

    def edit_road(self):
        i=self.road_list.currentRow()
        if i<0:return
        dialog=RoadDialog(self.project['roads'][i],self)
        if dialog.exec()==QDialog.Accepted:self.snapshot();self.project['roads'][i].update(dialog.values());self.changed()

    def delete_road(self):
        i=self.road_list.currentRow()
        if i>=0:self.snapshot();self.project['roads'].pop(i);self.map.selected_road=None;self.changed()

    def edit_note(self):
        i=self.note_list.currentRow()
        if i<0:return
        dialog=NoteDialog(self.project['notes'][i],self)
        if dialog.exec()==QDialog.Accepted:self.snapshot();self.project['notes'][i].update(dialog.values());self.changed()

    def delete_note(self):
        i=self.note_list.currentRow()
        if i>=0:self.snapshot();self.project['notes'].pop(i);self.changed()

    def edit_avoid(self):
        i=self.avoid_list.currentRow()
        if i<0:return
        zone=self.project['avoid'][i];scale=self.project['meters_per_pixel'] or 1
        if zone.get('shape')=='rect':
            width,ok=QInputDialog.getDouble(self,'危险区域','宽度（米）',zone['width']*scale,10,10000,0)
            if not ok:return
            height,ok=QInputDialog.getDouble(self,'危险区域','高度（米）',zone['height']*scale,10,10000,0)
            if ok:self.snapshot();zone.update(width=width/scale,height=height/scale);self.changed()
            return
        value,ok=QInputDialog.getInt(self,'避让区域','半径（米）',round(zone['radius']*scale),10,3000)
        if ok:self.snapshot();zone['radius']=value/scale;self.changed()

    def delete_avoid(self):
        i=self.avoid_list.currentRow()
        if i>=0:self.snapshot();self.project['avoid'].pop(i);self.changed()

    def add_danger_region(self,region):
        def apply():
            self.snapshot();self.project['avoid'].append(region);self.changed();self.notify('危险区域已保存。'+('已找到绕行路线。' if self.route else self.route_label.text())+' 拖动中心或右下角可调整。')
        QTimer.singleShot(0,apply)

    def delete_waypoint(self):
        i=self.waypoint_list.currentRow()
        if i>=0:self.snapshot();self.project['waypoints'].pop(i);self.changed()

    def clear_button(self,key,location):
        waypoint=key=='waypoints'
        label='清空途经点' if waypoint else '清空危险区'
        button=self.button(label,lambda:self.clear_annotations(key))
        button.setObjectName('clear_'+key+'_'+location)
        button.setToolTip('仅清除当前地图的'+('途经点' if waypoint else '危险区域')+'；保留目的地、道路与收藏，可撤销')
        (self.clear_waypoint_buttons if waypoint else self.clear_avoid_buttons).append(button)
        return button

    def clear_annotations(self,key):
        if key not in ('waypoints','avoid') or not self.project[key]:return
        count=len(self.project[key]);self.snapshot();self.project[key]=[];self.changed()
        self.notify(f"已清空 {count} 个{'途经点' if key=='waypoints' else '危险区域'}，可点击撤销恢复")

    def clear_route_button(self,location):
        button=self.button('清除当前路线',self.clear_current_route)
        button.setObjectName('clear_current_route_'+location)
        button.setToolTip('停止导航并清除起始点、目的地、途经点和路线；保留图标显隐状态、已保存的道路、收藏、危险区与路线规则')
        return button

    def clear_current_route(self):
        if self.project['start'] is not None or self.project['destination'] is not None or self.project['waypoints'] or self.active_favorite():self.snapshot()
        self.project['start']=None;self.project['destination']=None;self.project['waypoints']=[];self.detach_favorite()
        self.changed(replan=False)
        self.navigator=Navigator();self.minimap_overlay.points=[];self.minimap_overlay.full_points=[];self.worker.path_mask=None
        self.route_label.setText('路线已清除；请选择新的目的地')
        self.set_hud({'state':'idle','text':'路线已清除'})
        self.notify('路线、起始点、目的地和途经点已清除，导航已停止；可撤销恢复行程设置')

    def set_start(self,point):
        self.snapshot();self.project['start']=list(point);self.favorite_trip=None;self.changed()
        self.notify('起始点已更新；往返时返回此点，修改目的地不会覆盖起始点')

    def use_current_start(self):
        if not (self.fix_live and self.fix and self.fix.valid and time.monotonic()-self.fix_time<2.5):
            self.notify('请先开启定位并取得当前有效位置，再设置起始点');return
        self.set_start([self.fix.x,self.fix.y])

    def move_item(self,key,p):
        # The scene item emits on mouse release; defer rebuilding its scene until
        # the event handler has returned to Qt.
        def apply():
            self.snapshot();kind=key[0]
            if kind=='road':
                road=next(r for r in self.project['roads'] if r['id']==key[1]);old=road['points'][key[2]]
                for r in self.project['roads']:
                    r['points']=[list(p) if distance(old,q)<1.5 else q for q in r['points']]
            elif kind=='start':self.project['start']=p;self.favorite_trip=None
            elif kind=='destination':self.detach_favorite();self.project['destination']=p
            elif kind=='waypoint':self.detach_favorite();self.project['waypoints'][key[1]]=p
            elif kind=='note':self.project['notes'][key[1]]['point']=p
            elif kind=='avoid':self.project['avoid'][key[1]]['point']=p
            elif kind=='avoid_resize':
                z=self.project['avoid'][key[1]];z['width']=max(4,abs(p[0]-z['point'][0])*2);z['height']=max(4,abs(p[1]-z['point'][1])*2)
            self.changed()
        QTimer.singleShot(0,apply)

    def remove_item(self,key):
        def apply():
            self.snapshot();kind=key[0]
            if kind=='road':
                road=next(r for r in self.project['roads'] if r['id']==key[1])
                if len(road['points'])<=2:self.notify('道路至少需要两个点；可在列表删除整条道路');return
                road['points'].pop(key[2])
            elif kind=='start':
                self.project['start']=None;self.favorite_trip=None;self.stop_navigation(quiet=True)
            elif kind=='destination':self.detach_favorite();self.project['destination']=None
            elif kind=='waypoint':self.detach_favorite();self.project['waypoints'].pop(key[1])
            elif kind=='note':self.project['notes'].pop(key[1])
            elif kind in ('avoid','avoid_resize'):self.project['avoid'].pop(key[1])
            self.changed()
        QTimer.singleShot(0,apply)

    def toggle_roads(self,value):self.map.show_roads=value;self.refresh_map()

    def undo(self):
        if not self.history:self.notify('没有可撤销的更改');return
        self.project=self.history.pop();self.favorite_trip=None;self.sync_policy();self.changed();self.update_scale_label();self.notify('已撤销上一步')

    def sync_policy(self):
        for k,w in self.kind_checks.items():w.blockSignals(True);w.setChecked(k in self.project['policy']['allowed']);w.blockSignals(False)
        self.roundtrip.blockSignals(True);self.roundtrip.setChecked(self.project['roundtrip']);self.roundtrip.blockSignals(False)

    def change_policy(self):
        if not hasattr(self,'kind_checks'):return
        self.snapshot();self.project['policy']={'allowed':[k for k,w in self.kind_checks.items() if w.isChecked()],'confirmed_only':False};self.project['roundtrip']=self.roundtrip.isChecked();self.changed()

    def choose_destination(self,index):
        if index>0:self.snapshot();self.detach_favorite();self.project['destination']=list(self.project['destinations'][index-1]['point']);self.changed()

    def save_destination(self):
        if not self.project['destination']:self.notify('请先在地图选择目的地');return
        name,ok=QInputDialog.getText(self,'收藏目的地','名称')
        if ok and name.strip():self.snapshot();self.project['destinations'].append({'name':name.strip(),'point':list(self.project['destination'])});self.changed()

    def import_project(self):
        path,_=QFileDialog.getOpenFileName(self,'导入导航配置','','JSON 配置 (*.json)')
        if not path:return
        try:data=read_project(path)
        except (OSError,ValueError,TypeError,KeyError) as error:self.notify(f'配置未导入：{error}');return
        if data['map']!=self.project['map'] and not self.switch_map(data['map']):return
        self.snapshot();self.project=data;self.favorite_trip=None;self.sync_policy();self.changed();self.update_scale_label();self.notify('已导入完整配置，可撤销恢复')

    def export_project(self):
        path,_=QFileDialog.getSaveFileName(self,'导出完整导航配置',map_info(self.project['map'])['name']+'-导航配置.json','JSON 配置 (*.json)')
        if not path:return
        try:atomic_json(path,validate_project(self.project));self.notify('配置已导出：'+path)
        except (OSError,ValueError,TypeError) as error:self.notify(f'导出失败：{error}')

    def preview_route(self):
        if self.navigator.active:
            if self.fix_live and self.fix and self.fix.valid:self.replan_navigation()
            else:self.notify('等待有效实时定位后再重算当前路线')
        else:self.plan_route(preview_full=True)

    def plan_route(self,*_,quiet=False,anchors=None,preview_full=False):
        saved=self.active_favorite()
        returning=bool(anchors is not None and self.navigator.lap%2)
        current=anchors[0] if anchors else None
        if anchors is None and not saved:
            origin=self.project['start'] or ([self.fix.x,self.fix.y] if self.fix and self.fix.valid else None)
            if origin is None:
                if not quiet:self.notify('请先设置起始点或开启定位')
                return False
            if not self.project['destination']:
                if not quiet:self.notify('请先在地图选择目的地')
                return False
            anchors=[origin,*self.project['waypoints'],self.project['destination']]
        complete=True
        try:
            p=self.project['policy']
            if saved:
                journey=self.favorite_trip if self.favorite_trip and not preview_full else saved
                if journey is self.favorite_trip:
                    self.route=follow_saved(self.project['roads'],journey,p,self.project['avoid'],current,returning)
                    self.full_route=self.route
                    if current is not None:
                        try:self.full_route=follow_saved(self.project['roads'],journey,p,self.project['avoid'],reverse=returning)
                        except RouteError:complete=False
                else:
                    full=follow_saved(self.project['roads'],journey,p,self.project['avoid'],self.project['start'],self.project.get('active_route_reverse',False))
                    trip=saved_route('本次完整往返',full,snap_to_roads=saved.get('snap_to_roads',False),build_roads=saved.get('build_roads',True))
                    self.full_route=full.reversed() if returning else full
                    self.route=follow_saved(self.project['roads'],trip,p,self.project['avoid'],current,returning) if current is not None else self.full_route
                    if self.project['start'] is not None and not preview_full:self.favorite_trip=trip
            else:
                self.route=plan(self.project['roads'],anchors,p['allowed'],p['confirmed_only'],self.project['avoid'])
                self.full_route=self.route
                if self.project['start'] is not None:
                    full_anchors=[self.project['start'],*self.project['waypoints'],self.project['destination']]
                    if returning:full_anchors.reverse()
                    if full_anchors!=anchors:
                        try:self.full_route=plan(self.project['roads'],full_anchors,p['allowed'],p['confirmed_only'],self.project['avoid'])
                        except RouteError:complete=False
        except RouteError as error:
            self.route=None;self.full_route=None;self.route_label.setText(str(error));self.refresh_map()
            if not quiet:self.notify(str(error))
            return False
        scale=self.project['meters_per_pixel'];length=self.route.length*(scale or 1)
        total=f'{length/1000:.2f} km' if scale else f'{length:.0f} 地图单位'
        self.route_label.setText(f"{total} · {len(self.project['waypoints'])} 个途经点\n端点吸附偏移 {max(self.route.snap_distances)*(scale or 1):.0f} {'m' if scale else '单位'}")
        if not complete:self.route_label.setText(self.route_label.text()+'\n完整路线暂不可达，显示当前可行路段；起始点保持不变')
        self.refresh_map()
        if not quiet:self.notify('已沿完整收藏规划，危险区局部绕行' if saved else '路线已规划；拖动绿点可调整必经位置')
        return True

    def preview_cues(self):
        if not self.route:self.notify('请先预览路线');return
        dialog=QDialog(self);dialog.setWindowTitle('播报预览 · 当前路线');dialog.resize(700,550)
        layout=QVBoxLayout(dialog)
        layout.addWidget(self.text('同一路线的两种模式；距离为自起点沿路线累计。WRC 估算弯级可在地图标注中覆盖。',True))
        pages=QTabWidget();layout.addWidget(pages)
        scale=self.project['meters_per_pixel'] or 1
        lists={}
        for mode,label in [('normal','常规 · 路口与沿路距离'),('wrc','WRC · 连续路书')]:
            listing=QListWidget();cues=cues_for(self.route,self.project['notes'],mode,scale)
            if mode=='normal' and cues:listing.addItem('起步：沿当前道路行驶'+distance_text(cues[0].at*scale,self.project['meters_per_pixel'] is not None))
            for cue in cues:
                listing.addItem(f'{cue.at*scale:.0f} '+('m' if self.project['meters_per_pixel'] else '单位')+'  ·  '+cue_text(cue,mode,spoken=True)+('  [估算]' if cue.inferred else ''))
            pages.addTab(listing,label);lists[mode]=listing
        pages.setCurrentIndex(1 if self.settings['mode']=='wrc' else 0)
        layout.addWidget(self.button('试听选中条目',lambda:self.speak(pages.currentWidget().currentItem().text().replace('[估算]','')) if pages.currentWidget().currentItem() else None))
        layout.addWidget(self.button('关闭',dialog.accept));dialog.exec()

    def toggle_capture(self):
        self.worker.capture=not self.worker.capture
        if self.worker.capture:
            self.failure_diagnostic=None
            self.worker.wake.set();self.capture_button.setText('关闭定位');self.notify('正在读取指定区域；请让游戏小地图保持可见')
        else:
            self.stop_navigation(quiet=True);self.invalidate_fix('定位已关闭')
            self.fix_label.setText('定位已关闭');self.set_hud({'state':'idle','text':'定位已关闭'})

    def start_navigation(self):
        if not self.project['destination']:self.notify('请先选择目的地');return
        if not self.worker.isRunning():self.notify('视觉定位未就绪，请等待初始化或重新启动');return
        self.pending_start=True
        if not self.worker.capture:self.toggle_capture()
        if self.fix_live and self.fix and self.fix.valid and time.monotonic()-self.fix_time<2.5:self.begin_navigation()
        else:self.notify('正在获取实时位置；定位成功后自动开始导航')

    def begin_navigation(self):
        self.pending_start=False
        if not (self.fix and self.fix.valid):return
        self.favorite_trip=None;self.navigator.lap=0
        if self.project['start'] is None:
            self.snapshot();self.project['start']=[self.fix.x,self.fix.y];self.autosave.start();self.refresh_lists();self.refresh_map()
        anchors=[[self.fix.x,self.fix.y],*self.project['waypoints'],self.project['destination']]
        if not self.plan_route(quiet=True,anchors=anchors):return
        self.navigator.start(self.route,self.project['notes'],self.settings,self.project['meters_per_pixel'],self.project['roundtrip'])
        self.update_minimap_overlay()
        self.hud.show();self.notify('导航已开始 · 定位失效时暂停播报')

    def stop_navigation(self,*_,quiet=False):
        self.minimap_overlay.hide()
        self.navigator.stop();self.pending_start=False;self.tts.stop();self.set_hud({'state':'idle','text':'导航已停止'})
        if not quiet:self.notify('导航已停止')

    def worker_error(self,text,map_id=None,generation=0):
        if map_id is not None and ((map_id,generation)!=self.worker.context or map_id!=self.project['map']):return
        self.fix=Fix(reason=text,map_id=self.worker.context[0],generation=self.worker.context[1])
        self.remember_frame(self.fix,None,'worker_error')
        self.invalidate_fix(text);self.notify(text)

    def invalidate_fix(self,reason):
        self.fix_live=False
        self.fix=replace(self.fix,valid=False,reason=reason) if self.fix else Fix(reason=reason)
        self.map.update_fix(self.fix)
        self.minimap_overlay.hide()
        self.capture_button.setText('关闭定位' if self.worker.capture else '开启定位')
        self.fix_label.setText('定位丢失 · 已暂停播报');self.fix_detail.setText(reason)
        self.navigator.lost();self.tts.stop();self.set_hud({'state':'lost','text':'定位丢失'})

    def remember_frame(self,fix,frame,source):
        self.frame=frame
        self.frame_diagnostic=(frame,{'version':__version__,'source':source,'received_at':time.time(),
            'frame_available':frame is not None,'fix':asdict(fix),
            'capture':deepcopy(self.settings['capture']),'anchor':list(self.settings['anchor']),
            'north_up':self.settings['north_up']})
        if not fix.valid:self.failure_diagnostic=self.frame_diagnostic
        if frame is None:
            self.preview.clear();self.preview.setText('本次未取得截图；可保存错误诊断 JSON')
        else:
            rgb=frame[:,:,::-1].copy();h,w=rgb.shape[:2];image=QImage(rgb.data,w,h,rgb.strides[0],QImage.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(image).scaled(285,170,Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def on_fix(self,fix,frame,live):
        if fix.map_id is not None and ((fix.map_id,fix.generation)!=self.worker.context or fix.map_id!=self.project['map']):return
        if live and not self.worker.capture:return
        now=time.monotonic()
        if not live:self.failure_diagnostic=None
        if fix.valid and live and self.last_accepted and now-self.last_accepted_time<8:
            jump=distance([fix.x,fix.y],self.last_accepted)*(self.project['meters_per_pixel'] or 1)
            if jump>max(80,80*(now-self.last_accepted_time)):
                if self.jump_candidate and distance([fix.x,fix.y],self.jump_candidate)<12:self.jump_count+=1
                else:self.jump_candidate=[fix.x,fix.y];self.jump_count=1
                if self.jump_count<3:fix.valid=False;fix.reason='位置突变，正在重新确认'
            else:self.jump_count=0
        self.fix=fix;self.fix_live=live and fix.valid;self.fix_time=now
        self.remember_frame(fix,frame,'live' if live else 'image')
        self.map.update_fix(fix)
        if fix.valid:
            self.fix_label.setText(('实时定位' if live else '图片检验')+f' · {fix.confidence:.0%}')
            heading=f'{fix.heading:.0f}°' if fix.heading is not None else '未知'
            self.fix_detail.setText(f'位置 {fix.x:.1f}, {fix.y:.1f}  ·  匹配点 {fix.inliers}\n误差 {fix.error:.2f}px  ·  朝向 {heading}')
            if live:self.last_accepted=[fix.x,fix.y];self.last_accepted_time=now
        else:
            self.invalidate_fix(fix.reason);return
        if self.pending_start and live:self.begin_navigation()
        if self.navigator.active and live:
            data=self.navigator.update([fix.x,fix.y],now)
            if data:
                self.set_hud(data)
                if data.get('state')=='offroute':self.tts.stop()
                if data.get('speech'):self.speak(data['speech'])
                if data.get('state')=='turnaround':self.next_leg()
                if data.get('replan'):self.replan_navigation()
                if data.get('state')=='arrived':self.notify('已到达目的地')
        self.update_minimap_overlay()

    def replan_navigation(self):
        old=self.navigator;waypoints=list(self.project['waypoints'])
        if old.lap%2:waypoints.reverse()
        remaining=[]
        for p in waypoints:
            projection=nearest_on_route(p,old.route.points)
            if projection and projection[1]>old.progress+3:remaining.append(p)
        goal=self.project['start'] if old.lap%2 else self.project['destination']
        lap,leg=old.lap,old.leg
        if self.plan_route(quiet=True,anchors=[[self.fix.x,self.fix.y],*remaining,goal]):
            self.tts.stop()
            old.start(self.route,self.project['notes'],self.settings,self.project['meters_per_pixel'],self.project['roundtrip']);old.lap=lap;old.leg=leg
            self.speak('路线已重新规划');self.notify('已按原路线规则与剩余途经点重算')
        else:
            old.stop();self.tts.stop();self.set_hud({'state':'offroute','text':'无可行路线'});self.notify('偏航后未找到可行路线，请调整道路或途经点')

    def next_leg(self):
        # Rebuild from the original journey endpoints even after an earlier
        # off-route replan shortened the currently followed leg.
        lap,leg=self.navigator.lap,self.navigator.leg
        waypoints=list(self.project['waypoints'])
        if lap%2:waypoints.reverse()
        goal=self.project['start'] if lap%2 else self.project['destination']
        if self.plan_route(quiet=True,anchors=[[self.fix.x,self.fix.y],*waypoints,goal]):
            self.navigator.start(self.route,self.project['notes'],self.settings,self.project['meters_per_pixel'],self.project['roundtrip']);self.navigator.lap=lap;self.navigator.leg=leg
        else:
            self.navigator.stop();self.tts.stop();self.set_hud({'state':'offroute','text':'返程道路不连通'});self.notify('下一程没有可行路线，请调整危险区或道路规则')

    def check_stale(self):
        if time.monotonic()-self.fix_time>2.5:
            self.minimap_overlay.hide()
        keep_on_top(self.hud)
        if self.minimap_overlay.isVisible():keep_on_top(self.minimap_overlay)
        if self.fix_live and time.monotonic()-self.fix_time>2.5:
            self.invalidate_fix('超过 2.5 秒未收到有效实时位置，等待重新定位')

    def select_region(self):
        self.worker.capture=False;self.capture_button.setText('开启定位');self.stop_navigation(quiet=True)
        if not self.monitors:self.notify('未找到可捕获的显示器');return
        index=max(0,self.screen_combo.currentIndex());monitor=self.monitors[index]
        self.hide();self.hud.hide()
        def grab():
            try:
                import mss
                with mss.MSS() as sct:frame=np.asarray(sct.grab(monitor))[:,:,:3].copy()
                self.show();dialog=RegionDialog(frame,monitor,self)
                if dialog.exec()==QDialog.Accepted:
                    self.settings['capture'].update(dialog.region)
                    for key,field in self.capture_fields.items():field.setValue(dialog.region[key])
                    self.save_settings();self.notify('识别区域已保存；确认玩家锚点后开启定位')
            except Exception as error:self.show();self.notify(f'无法捕获显示器：{error}')
        QTimer.singleShot(350,grab)

    def capture_setting(self,key,value):
        self.settings['capture'][key]=value;self.fix_live=False;self.save_settings()

    def anchor_setting(self):self.settings['anchor']=[self.anchor_x.value()/100,self.anchor_y.value()/100];self.fix_live=False;self.save_settings()

    def set_setting(self,key,value):
        self.settings[key]=value
        if key=='voice_rate':self.tts.setRate(value)
        self.save_settings()

    def set_main_topmost(self,value):
        self.settings['main_topmost']=value;self.setWindowFlag(Qt.WindowStaysOnTopHint,value);self.show();self.save_settings()

    def overlay_setting(self,key,value):
        self.settings['minimap_overlay'][key]=value;self.save_settings();self.update_minimap_overlay()

    def update_minimap_overlay(self):
        if not (self.navigator.active and self.fix_live and self.fix and self.fix.valid and self.frame is not None):
            self.minimap_overlay.hide();return
        self.minimap_overlay.update_route(self.route,self.fix,(self.frame.shape[1],self.frame.shape[0]),self.settings['anchor'],self.settings['capture'],full_route=self.full_route,progress=self.navigator.progress)
        if self.minimap_overlay.capture_excluded is False:
            self.overlay_status.setText('路径已显示；当前系统在定位时滤除路径区域，避免叠加线参与匹配。鼠标穿透，定位丢失时自动隐藏。')

    def save_capture_diagnostic(self):
        is_failure=self.failure_diagnostic is not None
        snapshot=self.failure_diagnostic or self.frame_diagnostic
        if snapshot is None:self.notify('先开启定位，或用图片检验，再保存诊断');return
        frame,metadata=snapshot
        has_frame=frame is not None
        path,_=QFileDialog.getSaveFileName(self,'保存定位诊断',
            '定位诊断.png' if has_frame else '定位诊断.json','PNG (*.png)' if has_frame else 'JSON (*.json)')
        if not path:return
        try:
            import cv2
            target=Path(path)
            if has_frame:cv2.imencode('.png',frame)[1].tofile(str(target.with_suffix('.png')))
            metadata=dict(metadata,selected='latest_failure' if is_failure else 'latest_frame',
                          saved_at=time.time(),current_fix=asdict(self.fix) if self.fix else None)
            atomic_json(target.with_suffix('.json'),metadata)
            self.notify('已保存最近失败帧 PNG 与诊断 JSON' if has_frame and is_failure else
                        '已保存小地图 PNG 与诊断 JSON' if has_frame else '未取得截图；已保存错误诊断 JSON')
        except (OSError,ValueError,cv2.error) as error:self.notify(f'保存失败：{error}')

    def hud_setting(self,key,value):self.settings['hud'][key]=value;self.hud.apply_settings();self.save_settings()

    def change_mode(self):
        self.settings['mode']=self.mode.currentData();self.tts.stop();self.save_settings()
        if self.navigator.active:
            self.navigator.cues=cues_for(self.navigator.route,self.project['notes'],self.settings['mode'],self.project['meters_per_pixel'] or 1);self.navigator.spoken.clear()
            self.set_hud({'state':'idle','text':'WRC 路书' if self.settings['mode']=='wrc' else '常规导航'})
        else:self.set_hud({'state':'idle','text':'等待导航'})

    def set_hud(self,data):self.hud.set_data(data,self.settings['mode'],self.project['meters_per_pixel'] is not None)

    def show_hud(self):
        if not self.navigator.active:self.set_hud({'state':'idle','text':'等待导航'})
        self.hud.show()

    def reset_hud(self):
        rect=QApplication.primaryScreen().availableGeometry();self.settings['hud'].update(x=rect.x()+rect.width()//2-200,y=rect.y()+50)
        for key in ('x','y'):self.hud_fields[key].setValue(self.settings['hud'][key])
        self.hud.apply_settings();self.hud.show();self.save_settings()

    def load_voices(self):
        self.voices=self.tts.availableVoices();self.voice_combo.blockSignals(True);self.voice_combo.clear()
        for voice in self.voices:self.voice_combo.addItem(voice.name()+' · '+voice.locale().name())
        chosen=next((i for i,v in enumerate(self.voices) if v.name()==self.settings['voice_name']),None)
        if chosen is None:chosen=next((i for i,v in enumerate(self.voices) if v.locale().language()==QLocale.Chinese),0)
        self.voice_combo.setCurrentIndex(chosen);self.voice_combo.blockSignals(False)
        if self.voices:self.select_voice(chosen);self.voice_status.setText('本机系统语音 · 离线播报')
        else:self.voice_status.setText('未发现系统语音；请安装 Windows 中文语音包后重启')
        self.tts.setRate(self.settings['voice_rate'])

    def select_voice(self,index):
        if 0<=index<len(self.voices):self.tts.setVoice(self.voices[index]);self.settings['voice_name']=self.voices[index].name();self.save_settings()

    def change_voice(self,value):self.settings['voice']=value;self.tts.stop();self.save_settings()

    def speak(self,text):
        if self.settings['voice'] and self.voices:self.tts.enqueue(text)

    def test_voice(self):
        if not self.voices:self.load_voices()
        if not self.voices:self.notify('系统语音不可用：请检查 Windows 设置 → 时间和语言 → 语音');return
        self.tts.stop();self.tts.say('沿当前道路行驶八百米。前方一百米，路口直行。下个路口右转。' if self.settings['mode']=='normal' else '一百米，左三，收紧，接，右六。五十米，急刹车，接，左直角，别切。')

    def test_image(self):
        path,_=QFileDialog.getOpenFileName(self,'用小地图图片检验定位','','地图截图 (*.png *.jpg *.jpeg *.bmp)')
        if path:
            self.failure_diagnostic=None
            self.worker.capture=False;self.capture_button.setText('开启定位');self.stop_navigation(quiet=True);self.worker.request_sample(path);self.notify('正在检验图片；实时导航需重新开启定位')

    def update_scale_label(self):
        scale=self.project['meters_per_pixel'];text=f'{scale:.4f} 米 / 地图像素' if scale else '尚未标定 · 使用地图单位'
        self.scale_label.setText(text+'\n'+self.project.get('calibration',{}).get('status',''))

    def set_scale(self):
        value,ok=QInputDialog.getDouble(self,'距离比例尺','每个地图像素对应的米数',self.project['meters_per_pixel'] or 1,.01,1000,4)
        if ok:self.snapshot();self.project['meters_per_pixel']=value;self.project['calibration']={'source':'用户直接输入','status':'用户校准'};self.changed();self.update_scale_label()

    def help(self):
        QMessageBox.information(self,'使用说明',
            '1. 保留游戏全屏模式，小地图固定北朝上。叠加显示依赖 Windows 全屏优化；若被遮挡再尝试无边框全屏。\n'
            '2. 在顶部选择当前游戏地图，再框选小地图，调整玩家锚点（默认区域中心），开启定位。\n'
            '3. 地图点选终点；拖框标记危险区，路线自动绕开。也可拖动途经点指定必经位置。\n'
            '4. 起始点可地图设置、拖动或使用当前位置；也是往返的返程终点。未设置时，开始导航会用当前有效位置放置，途中改目的地不会覆盖。小地图淡线为完整路线，亮线为随前进缩短的剩余路程。\n'
            '5. “移动 / 选路”下单击道路选中并拖点；双击编辑属性，右键编辑或删除。绘路时 Enter 完成、Esc 取消，Ctrl+Z 撤销。WRC 1 为慢弯、6 为快弯，手动路书优先。\n\n'
            '6. 绘路可选大路、小路或野地；Backspace 退一点。路网可单独导入导出。\n'
            '7. 收藏可勾选“贴合现有道路”，粗略放点后预览沿路路径。关闭时保留完整走法并选择是否建立道路。导入同样确认选项；不建路也可导航，仅该收藏使用。导出保留完整路径、类型、粗绘点、选项与路书，可反向载入。收藏仍遵守危险区与道路规则。\n'
            '8. 常规提示路口动作和沿路距离；WRC 提示弯级、直角和手动急刹车等，显示后续三条路书。两种模式提前量独立调整，可在导航页查看播报列表。\n\n'
            '9. OZETI、BAKURANI、ZESTAFONA 分别保存道路、收藏、危险区、路书和比例尺。切图会保存当前配置并停止导航；重新开启定位后继续。完整配置导入会切至对应地图，路网和收藏资料库需先切到同一地图再合并。\n\n'
            '道路按分类直接参与规划，无需设置确认状态；地图道路统一用虚线，导航路线保持实线。“清除当前路线”会停止导航，清掉本次起始点、目的地、途经点和路线显示，并退出当前收藏；图标保持原来的显隐状态，已保存的道路、收藏和危险区保留。可撤销恢复行程设置，重新开始导航需手动点击。途经点和危险区也可分别清空。路线端点吸附到道路，不包含未知地形的末段引导。图片无法识别地雷、实时路障或证明越野可通行。\n'
            '仅获取指定屏幕区域，不读取游戏内存或自动控制载具。第三方工具许可仍以游戏方规定为准。\n\n'
            f'配置自动保存在：{user_dir()}\n导出 JSON 可备份或共享完整地图配置。')

    def closeEvent(self,event):
        self.minimap_overlay.close()
        self.watchdog.stop();self.autosave.stop();self.tts.stop();self.hud.close();self.worker.shutdown();self.save_project();self.save_settings();event.accept()


def run():
    app=QApplication.instance() or QApplication([])
    app.setApplicationName('WardogsNavigator');app.setOrganizationName('WardogsNavigator')
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    window=MainWindow();window.show()
    return app.exec()
