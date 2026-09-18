from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[1]
assets=ROOT/'assets'
legacy=assets/'legacy-road-seed.json'
if not legacy.exists():shutil.copy2(assets/'default_project.json',legacy)
previous=json.loads(legacy.read_text(encoding='utf-8'))
roads=json.loads((ROOT/'research/extracted-roads.json').read_text(encoding='utf-8'))['roads']
meta=json.loads((ROOT/'research/clean-registration.json').read_text(encoding='utf-8'))
meta['reference']='public grayscale z5 tiles (development source); runtime uses ozeti-features.npz'
data=dict(previous,roads=roads,road_data_revision=2,meters_per_pixel=2/meta['reference_to_map'][0][0],calibration={'source':'公开 OZETI 瓦片边界 16384 米 / z5 像素 + 地图配准','status':'公开地图比例尺；可用游戏内两点复核'})
(assets/'default_project.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copy2(ROOT/'research/clean-aligned.png',assets/'ozeti.png')
(assets/'map-source.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
# The retained upstream license is already present in assets.
print('published clean map and',len(roads),'roads')
