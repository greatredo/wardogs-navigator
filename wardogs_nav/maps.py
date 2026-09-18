"""Bundled map metadata and per-map storage; OZETI keeps its original paths."""
from functools import lru_cache
import json
from .model import asset_path,user_dir


@lru_cache(maxsize=1)
def all_maps():
    return tuple(json.loads(asset_path('maps.json').read_text(encoding='utf-8')))


def map_info(map_id):
    found=next((m for m in all_maps() if m['id']==map_id),None)
    if found is None:raise ValueError(f'不支持的地图：{map_id}')
    return found


def map_asset(map_id,key):
    return asset_path(map_info(map_id)[key])


def project_path(map_id):
    map_info(map_id)
    return user_dir()/'project.json' if map_id=='ozeti' else user_dir()/'maps'/map_id/'project.json'


def load_map_project(map_id):
    from .model import read_project
    path=project_path(map_id)
    data=read_project(path if path.exists() else map_asset(map_id,'project'))
    if data['map']!=map_id:raise ValueError('此地图的配置文件中包含另一张地图，请从完整配置导入入口恢复')
    return data
