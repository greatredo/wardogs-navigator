from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
import math
import os
import sys
import uuid

KINDS = {'major': '大路', 'minor': '小路', 'offroad': '野地 / 越野'}
NOTE_TYPES = {'left': '左弯', 'right': '右弯', 'straight': '直行',
              'square_left': '左直角', 'square_right': '右直角',
              'hairpin_left': '左发卡', 'hairpin_right': '右发卡',
              'hard_brake': '急刹车', 'brake': '刹车', 'crest': '坡顶',
              'bump': '颠簸', 'jump': '跳跃', 'narrow': '变窄', 'bridge': '桥梁',
              'caution': '注意', 'water': '涉水'}
MODIFIERS = {'long': '长弯', 'tightens': '收紧', 'opens': '放开', 'dont_cut': '别切', 'cut': '可切'}


def uid():
    return uuid.uuid4().hex[:12]


def asset_path(name):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'assets' / name


def user_dir():
    override = os.environ.get('WARDOGS_NAV_DATA')
    if override:
        return Path(override)
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'WardogsNavigator'


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def default_settings():
    from .hotkeys import DEFAULT_HOTKEYS
    return {'map_id':'ozeti','capture': {'left': 0, 'top': 0, 'width': 340, 'height': 303},
            'anchor': [.5, .5], 'north_up': True, 'interval_ms': 700,
            'mode': 'normal', 'voice': True, 'voice_name': '', 'voice_rate': 0.,
            'lead_m': 100., 'lead_s': 4., 'arrival_m': 25., 'offroute_m': 80.,
            'wrc_lead_m': 150., 'wrc_lead_s': 5., 'wrc_chain_m': 60.,
            'main_topmost': False,
            'bigmap': {'enabled': False, 'opacity': .9, 'line_width': 4, 'avoid_radius_m': 50},
            'bigmap_capture': {'left': 0, 'top': 0, 'width': 800, 'height': 800},
            'bigmap_hotkeys': dict(DEFAULT_HOTKEYS),
            'minimap_overlay': {'enabled': True, 'opacity': .85, 'line_width': 4},
            'hud': {'x': 700, 'y': 60, 'width': 400, 'height': 170, 'opacity': .94, 'locked': False}}


def load_settings():
    defaults = default_settings()
    path = user_dir() / 'settings.json'
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            for key, value in defaults.items():
                if key in saved:
                    if isinstance(value, dict) and isinstance(saved[key], dict):
                        value.update({k: v for k, v in saved[key].items() if k in value})
                    elif isinstance(value,(int,float)) and not isinstance(value,bool) and isinstance(saved[key],(int,float)) and not isinstance(saved[key],bool) and math.isfinite(saved[key]):
                        defaults[key]=type(value)(saved[key])
                    elif isinstance(saved[key], type(value)):
                        defaults[key] = saved[key]
        except (OSError, ValueError, TypeError):
            pass
    return defaults


def validate_project(data):
    from .maps import map_info
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise ValueError('配置版本无效，仅支持 schema=1')
    info=map_info(data.get('map'))
    result = deepcopy(data)
    width, height = info['width'],info['height']
    def point(p):
        if not isinstance(p, (list, tuple)) or len(p) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in p):
            raise ValueError('坐标必须是两个有限数值')
        if not (0 <= p[0] <= width and 0 <= p[1] <= height):
            raise ValueError(f"坐标超出 {info['name']} 地图边界")
    scale = data.get('meters_per_pixel')
    if scale is not None and (isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or not .01 <= scale <= 1000):
        raise ValueError('距离比例尺无效')
    for key in ('roads', 'notes', 'avoid', 'waypoints', 'destinations'):
        if not isinstance(data.get(key), list) or len(data[key]) > 10000:
            raise ValueError(f'{key} 必须是列表且不超过 10000 项')
    ids = set()
    for road in data['roads']:
        if not isinstance(road,dict):raise ValueError('道路必须是对象')
        if road.get('kind') not in KINDS:
            raise ValueError('道路分类无效')
        if not isinstance(road.get('name'), str) or len(road['name']) > 200:
            raise ValueError('道路名称无效')
        if not isinstance(road.get('id'), str) or road['id'] in ids:
            raise ValueError('道路 ID 缺失或重复')
        ids.add(road['id'])
        if not 2 <= len(road.get('points', [])) <= 2000:
            raise ValueError('每条道路需要 2–2000 个节点')
        for p in road['points']:
            point(p)
    ids.clear()
    for note in data['notes']:
        if not isinstance(note,dict):raise ValueError('路书必须是对象')
        point(note.get('point'))
        if note.get('type') not in NOTE_TYPES or note.get('direction') not in ('both', 'forward', 'reverse'):
            raise ValueError('路书类型或方向无效')
        if not isinstance(note.get('id'), str) or note['id'] in ids:
            raise ValueError('路书 ID 缺失或重复')
        ids.add(note['id'])
        if not isinstance(note.get('grade'), int) or not 1 <= note['grade'] <= 6:
            raise ValueError('弯道等级必须为 1–6')
        for key in ('bearing', 'lead_m'):
            if not isinstance(note.get(key, 0), (float, int)) or not math.isfinite(note.get(key, 0)):
                raise ValueError('路书方向角或提前量无效')
        for key in ('text','reverse_text'):
            if not isinstance(note.get(key, ''), str) or len(note.get(key, '')) > 300:
                raise ValueError('路书文字无效或过长')
        if not 0<=note.get('bearing',0)<=360 or not 0<=note.get('lead_m',0)<=2000:
            raise ValueError('路书方向角或提前距离超出范围')
        if not isinstance(note.get('modifiers',[]),list) or any(m not in MODIFIERS for m in note.get('modifiers',[])):
            raise ValueError('路书修饰无效')
    for zone in data['avoid']:
        if not isinstance(zone,dict):raise ValueError('危险区必须是对象')
        point(zone.get('point'))
        if zone.get('shape') not in (None,'circle','rect'):raise ValueError('危险区域形状无效')
        if zone.get('shape')=='rect':
            for dimension in ('width','height'):
                value=zone.get(dimension)
                if not isinstance(value,(int,float)) or not math.isfinite(value) or not 1<=value<=max(2000,width,height):
                    raise ValueError('危险区域尺寸无效')
        elif not isinstance(zone.get('radius'), (int, float)) or not math.isfinite(zone['radius']) or not 1 <= zone['radius'] <= 1000:
            raise ValueError('避让半径无效')
    for p in data['waypoints']:
        point(p)
    for d in data['destinations']:
        if not isinstance(d,dict):raise ValueError('目的地必须是对象')
        point(d.get('point'))
        if not isinstance(d.get('name'), str) or len(d['name']) > 200:
            raise ValueError('目的地名称无效')
    if data.get('destination') is not None:
        point(data['destination'])
    if result.setdefault('start',None) is not None:
        point(result['start'])
    library = result.setdefault('route_library', [])
    if not isinstance(library,list) or len(library)>1000:
        raise ValueError('路线收藏必须为列表且不超过 1000 条')
    ids.clear()
    for saved in library:
        if not isinstance(saved,dict) or not isinstance(saved.get('id'),str) or saved['id'] in ids:
            raise ValueError('收藏路线 ID 缺失或重复')
        ids.add(saved['id'])
        if not isinstance(saved.get('name'),str) or not 1<=len(saved['name'])<=200:
            raise ValueError('收藏路线名称无效')
        pts=saved.get('points')
        if not isinstance(pts,list) or not 2<=len(pts)<=10000:
            raise ValueError('收藏路线需要 2–10000 个节点')
        for p in pts:point(p)
        kinds=saved.get('kinds')
        if not isinstance(kinds,list) or len(kinds)!=len(pts)-1 or any(k not in KINDS for k in kinds):
            raise ValueError('收藏路线各段分类无效')
        for key in ('snap_to_roads','build_roads'):
            if key in saved and not isinstance(saved[key],bool):raise ValueError('收藏贴路或建路设置无效')
        if 'control_points' in saved:
            controls=saved['control_points']
            if not isinstance(controls,list) or not 2<=len(controls)<=10000:raise ValueError('收藏粗绘点数量无效')
            for p in controls:point(p)
    active=result.get('active_route_id')
    if active is not None and active not in ids:
        raise ValueError('当前收藏路线不存在')
    if not isinstance(result.get('active_route_reverse',False),bool):
        raise ValueError('收藏路线方向无效')
    policy = result.setdefault('policy', {'allowed': ['major', 'minor'], 'confirmed_only': False})
    if not isinstance(policy,dict):raise ValueError('路线规则必须是对象')
    if not isinstance(policy.get('allowed'), list) or any(x not in KINDS for x in policy['allowed']):
        raise ValueError('路线规则无效')
    # Keep schema-1 compatibility fields, but road availability no longer has
    # a confirmation workflow. This does not assert real-world verification.
    for road in result['roads']:road['confirmed']=True
    policy['confirmed_only']=False
    if not isinstance(result.get('roundtrip', False), bool):
        raise ValueError('往返模式无效')
    return result


def read_project(path):
    if Path(path).stat().st_size > 15_000_000:
        raise ValueError('配置文件过大')
    return validate_project(json.loads(Path(path).read_text(encoding='utf-8')))


def upgrade_road_data(project):
    """Only migrate untouched bundled roads; never discard user road edits."""
    if project['map']!='ozeti':return project,False
    latest=read_project(asset_path('default_project.json'))
    if project.get('road_data_revision',1)>=latest.get('road_data_revision',1):return project,False
    previous=read_project(asset_path('legacy-road-seed.json'))
    old={r['id']:r for r in previous['roads']};current={r['id']:r for r in project['roads']}
    if any(current.get(key)!=value for key,value in old.items()):return project,False
    upgraded=deepcopy(project)
    upgraded['roads']=deepcopy(latest['roads'])+[deepcopy(r) for r in project['roads'] if r['id'] not in old]
    upgraded['road_data_revision']=latest['road_data_revision']
    if project.get('calibration')==previous.get('calibration'):
        upgraded['calibration']=latest['calibration'];upgraded['meters_per_pixel']=latest['meters_per_pixel']
    return validate_project(upgraded),True
