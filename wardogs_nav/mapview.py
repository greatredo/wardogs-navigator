from PySide6.QtCore import Qt, QPointF, Signal, QRectF
from PySide6.QtGui import QColor, QPen, QBrush, QPainterPath, QPixmap, QPainter, QPolygonF, QFont
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsItem, QMenu
from .maps import map_asset
from .routing import distance,project

COLORS = {'major':'#dbb865', 'minor':'#6caedb', 'offroad':'#99b274'}


class Handle(QGraphicsEllipseItem):
    def __init__(self, point, color, key, callback):
        super().__init__(-6, -6, 12, 12)
        self.setPos(*point)
        self.setBrush(QColor(color))
        self.setPen(QPen(QColor('#111923'), 2))
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIgnoresTransformations | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(20)
        self.key, self.callback = key, callback
        self.start = self.pos()

    def mousePressEvent(self, event):
        self.start = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        bounds=self.scene().sceneRect()
        x,y=max(bounds.left(),min(bounds.right()-1,self.pos().x())),max(bounds.top(),min(bounds.bottom()-1,self.pos().y()))
        self.setPos(x,y)
        if self.start != self.pos():
            self.callback(self.key, [x,y])


class MapView(QGraphicsView):
    clicked = Signal(float,float)
    finished = Signal()
    moved = Signal(object,object)
    remove_requested = Signal(object)
    hover = Signal(float,float)
    region_selected = Signal(object)
    road_selected = Signal(object)
    road_edit_requested = Signal(str)
    road_delete_requested = Signal(str)

    def __init__(self,map_id='ozeti'):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor('#10161c'))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.pixmap = QPixmap(str(map_asset(map_id,'image')))
        self.scene().setSceneRect(0,0,self.pixmap.width(),self.pixmap.height())
        self.project = None
        self.route = None
        self.fix = None
        self.selected_road = None
        self.draft = []
        self.draft_path = []
        self.tool = 'pan'
        self.press = None
        self.pressed_handle = False
        self.show_roads = True
        self.zoomed = False
        self.player_item = None
        self.danger_start = None
        self.danger_preview = None

    def load_map(self,map_id):
        pixmap=QPixmap(str(map_asset(map_id,'image')))
        if pixmap.isNull():raise ValueError('地图底图缺失或无法读取')
        self.pixmap=pixmap
        self.selected_road=None;self.draft=[];self.draft_path=[];self.fix=None;self.route=None
        self.danger_start=None;self.press=None;self.set_tool('pan')
        self.scene().setSceneRect(0,0,pixmap.width(),pixmap.height())
        self.redraw();self.fit()

    def fit(self):
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        self.zoomed = False

    def set_tool(self, tool):
        self.tool = tool
        self.setDragMode(QGraphicsView.ScrollHandDrag if tool == 'pan' else QGraphicsView.NoDrag)
        self.setCursor(Qt.OpenHandCursor if tool == 'pan' else Qt.CrossCursor)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        if .2 < self.transform().m11()*factor < 12:
            self.scale(factor,factor)
            self.zoomed = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.zoomed:
            self.fit()

    def mousePressEvent(self, event):
        self.press = event.position()
        self.pressed_handle=isinstance(self.itemAt(event.position().toPoint()),Handle)
        if self.tool in ('road','favorite') and event.button()==Qt.LeftButton:
            return
        if self.tool=='avoid' and event.button()==Qt.LeftButton and not isinstance(self.itemAt(event.position().toPoint()),Handle):
            self.danger_start=self.mapToScene(event.position().toPoint())
            return
        if event.button() == Qt.RightButton:
            p = self.mapToScene(event.position().toPoint())
            item = self.itemAt(event.position().toPoint())
            menu = QMenu(self)
            road_id=item.key[1] if isinstance(item,Handle) and item.key[0]=='road' else self.road_at(event.position().toPoint())
            if road_id:
                road=next(r for r in self.project['roads'] if r['id']==road_id)
                select=menu.addAction('选中道路 · '+road['name']);select.triggered.connect(lambda:self.road_selected.emit(road_id))
                edit=menu.addAction('编辑道路属性');edit.triggered.connect(lambda:self.road_edit_requested.emit(road_id))
                delete=menu.addAction('删除整条道路');delete.triggered.connect(lambda:self.road_delete_requested.emit(road_id))
                menu.addSeparator()
            if isinstance(item, Handle):
                key=item.key
                menu.addAction('删除此点 / 标注', lambda:self.remove_requested.emit(key))
            menu.addAction('在此设置目的地', lambda:self._context('destination',p))
            menu.addAction('在此添加途经点', lambda:self._context('waypoint',p))
            menu.addAction('在此添加路书', lambda:self._context('note',p))
            menu.addAction('在此添加避让区', lambda:self._context('avoid',p))
            menu.exec(event.globalPosition().toPoint())
            return
        super().mousePressEvent(event)

    def _context(self, tool, p):
        self.set_tool(tool)
        self.clicked.emit(p.x(),p.y())

    def mouseMoveEvent(self, event):
        p = self.mapToScene(event.position().toPoint())
        self.hover.emit(p.x(),p.y())
        if self.danger_start is not None:
            if self.danger_preview:self.scene().removeItem(self.danger_preview)
            r=QRectF(self.danger_start,p).normalized().intersected(self.sceneRect())
            self.danger_preview=self.scene().addRect(r,QPen(QColor('#f08888'),2),QBrush(QColor(210,55,65,70)))
            self.danger_preview.setZValue(15)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.tool in ('road','favorite') and event.button()==Qt.LeftButton:
            p=self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(p):self.clicked.emit(p.x(),p.y())
            return
        if self.danger_start is not None:
            p=self.mapToScene(event.position().toPoint())
            rect=QRectF(self.danger_start,p).normalized().intersected(self.sceneRect())
            self.danger_start=None
            if self.danger_preview:self.scene().removeItem(self.danger_preview);self.danger_preview=None
            if rect.width()>3 and rect.height()>3:
                self.region_selected.emit({'shape':'rect','point':[rect.center().x(),rect.center().y()],'width':rect.width(),'height':rect.height()})
            return
        item = self.itemAt(event.position().toPoint())
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or self.pressed_handle or isinstance(item, Handle):
            return
        if self.press is not None and (event.position()-self.press).manhattanLength() < 5:
            if self.tool=='pan':
                self.road_selected.emit(self.road_at(event.position().toPoint()))
                return
            p = self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(p):
                self.clicked.emit(p.x(),p.y())

    def mouseDoubleClickEvent(self, event):
        if self.tool in ('road','favorite'):
            self.finished.emit()
        elif self.tool=='pan' and event.button()==Qt.LeftButton:
            road_id=self.road_at(event.position().toPoint())
            if road_id:self.road_edit_requested.emit(road_id)
            else:super().mouseDoubleClickEvent(event)
        else:
            super().mouseDoubleClickEvent(event)

    def road_at(self,position):
        """Hit-test road geometry, including dash gaps, in screen-sized tolerance."""
        if not self.show_roads or self.project is None:return None
        p=self.mapToScene(position);point=[p.x(),p.y()]
        tolerance=8/max(self.transform().m11(),.01)
        nearest=(tolerance,None)
        for road in self.project['roads']:
            gap=min(project(point,a,b)[0] for a,b in zip(road['points'],road['points'][1:]))
            if gap<nearest[0]:nearest=(gap,road['id'])
        return nearest[1]

    def line(self, points, color, width=2, dashed=False, z=3):
        if not points:
            return
        path = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            path.lineTo(*point)
        pen = QPen(QColor(color),width)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if dashed:
            pen.setStyle(Qt.DashLine)
            pen.setDashPattern([16/width,12/width])
        item = self.scene().addPath(path,pen)
        item.setZValue(z)

    def label(self, text, point, color='#f4f6f7'):
        item = self.scene().addSimpleText(text,QFont('Microsoft YaHei UI',9))
        item.setBrush(QColor(color))
        item.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        item.setPos(point[0]+9, point[1]-10)
        item.setZValue(21)

    def handle(self, point, color, key):
        item = Handle(point,color,key,self.moved.emit)
        self.scene().addItem(item)
        return item

    def redraw(self):
        self.scene().clear()
        self.player_item = None
        self.danger_preview=None
        self.scene().addPixmap(self.pixmap)
        if self.project is None:
            return
        if self.show_roads:
            for road in self.project['roads']:
                selected = road['id'] == self.selected_road
                self.line(road['points'], '#ffffff' if selected else COLORS[road['kind']], 4 if selected else 2)
                if selected:
                    for i,p in enumerate(road['points']):
                        self.handle(p,'#f2cf75',('road',road['id'],i))
        for i, zone in enumerate(self.project['avoid']):
            x,y=zone['point']
            pen,brush=QPen(QColor('#ed7878'),2),QBrush(QColor(215,70,70,55))
            if zone.get('shape')=='rect':
                w,h=zone['width'],zone['height'];item=self.scene().addRect(x-w/2,y-h/2,w,h,pen,brush)
                self.handle([x+w/2,y+h/2],'#ed9898',('avoid_resize',i))
            else:
                r=zone['radius'];item=self.scene().addEllipse(x-r,y-r,2*r,2*r,pen,brush)
            item.setZValue(5)
            self.handle(zone['point'],'#e47878',('avoid',i))
            self.label('避让',zone['point'],'#ffb0b0')
        if self.route:
            self.line(self.route.points,'#102d2b',9,dashed=True,z=8)
            self.line(self.route.points,'#59e1bf',5,dashed=True,z=9)
            # Visual direction along the route.
            for i in range(0,len(self.route.points)-1,5):
                a,b=self.route.points[i:i+2]
                if distance(a,b) < 3:
                    continue
                p=((a[0]+b[0])/2,(a[1]+b[1])/2)
                self.label('·',p,'#ffffff')
        destination=self.project.get('destination')
        if destination:
            self.handle(destination,'#f2cf75',('destination',0))
            self.label('终点',destination,'#ffe5a1')
        for i,p in enumerate(self.project['waypoints']):
            self.handle(p,'#57dfbf',('waypoint',i))
            self.label(str(i+1),p,'#adf6e2')
        for i,note in enumerate(self.project['notes']):
            self.handle(note['point'],'#b296e5',('note',i))
            self.label('路书',note['point'],'#d7c6f4')
        if self.draft_path:self.line(self.draft_path,'#76e6c9',4,z=12)
        self.line(self.draft,'#ffffff',1 if self.draft_path else 3,True,13)
        for p in self.draft:
            self.scene().addEllipse(p[0]-2,p[1]-2,4,4,QPen(QColor('white')),QBrush(QColor('white')))
        self.update_fix(self.fix)

    def update_fix(self, fix):
        self.fix=fix
        if self.player_item:
            self.scene().removeItem(self.player_item)
            self.player_item=None
        if fix and fix.valid:
            poly=QPolygonF([QPointF(0,-13),QPointF(9,10),QPointF(0,5),QPointF(-9,10)])
            self.player_item=self.scene().addPolygon(poly,QPen(QColor('#0d2228'),2),QBrush(QColor('#f4ffff')))
            self.player_item.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            self.player_item.setPos(fix.x,fix.y)
            self.player_item.setRotation(fix.heading or 0)
            self.player_item.setZValue(30)
