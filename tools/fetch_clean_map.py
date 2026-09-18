"""Download only public image tiles covering a configured play area.

No game files, extraction tools or live game data are accessed.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.request import urlopen,Request
import argparse,json,math
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def fetch_map(map_id, zoom=5, color=False):
    folder=ROOT/'research' if map_id=='ozeti' else ROOT/'research/maps'/map_id
    folder.mkdir(parents=True,exist_ok=True)
    config_path=folder/'upstream-maps_ozeti.json' if map_id=='ozeti' else folder/'upstream.json'
    if not config_path.exists():
        with urlopen(f'https://raw.githubusercontent.com/apollyon-sys/wardogs-calculator/main/maps/{map_id}.json',timeout=30) as response:
            data=response.read()
        config=json.loads(data)
        if config.get('id')!=map_id:raise ValueError('Unexpected map configuration')
        config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    config=json.loads(config_path.read_text(encoding='utf-8'))
    z=zoom;size=256*2**z;tilebounds=config['tileBounds'];bounds=config['bounds']
    sx=size/(tilebounds['maxX']-tilebounds['minX']);sy=size/(tilebounds['maxY']-tilebounds['minY'])
    x0=math.floor((bounds['minX']-tilebounds['minX'])*sx);x1=math.ceil((bounds['maxX']-tilebounds['minX'])*sx)
    y0=math.floor((tilebounds['maxY']-bounds['maxY'])*sy);y1=math.ceil((tilebounds['maxY']-bounds['minY'])*sy)
    tile_x0,tile_x1=x0//256,(x1-1)//256;tile_y0,tile_y1=y0//256,(y1-1)//256
    style='color' if color else 'grayscale';url=config['tiles']['styles'][style]['path']
    cache=folder/f'tiles-{style}-{z}';cache.mkdir(parents=True,exist_ok=True)
    canvas=np.zeros(((tile_y1-tile_y0+1)*256,(tile_x1-tile_x0+1)*256,3),np.uint8)
    tasks=[(x,y) for y in range(tile_y0,tile_y1+1) for x in range(tile_x0,tile_x1+1)]
    def fetch(tile):
        x,y=tile;path=cache/f'{x}_{y}.webp'
        if not path.exists():
            req=Request(f'{url}/zoom_{z}/{x}_{y}.webp',headers={'User-Agent':'WardogsNavigator-map-preparation/0.4'})
            with urlopen(req,timeout=30) as response:data=response.read()
            image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
            if image is None or image.shape[:2]!=(256,256):raise RuntimeError(f'Invalid tile {tile}')
            path.write_bytes(data)
        image=cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_COLOR)
        return x,y,image
    completed=0
    with ThreadPoolExecutor(max_workers=6) as executor:
        for future in as_completed([executor.submit(fetch,t) for t in tasks]):
            x,y,image=future.result();left=(x-tile_x0)*256;top=(y-tile_y0)*256;canvas[top:top+256,left:left+256]=image
            completed+=1
            if completed%80==0 or completed==len(tasks):print(f'{map_id} {style} z{z}: {completed}/{len(tasks)}',flush=True)
    crop=canvas[y0-tile_y0*256:y1-tile_y0*256,x0-tile_x0*256:x1-tile_x0*256]
    destination=folder/f'clean-{style}-z{z}.png'
    cv2.imencode('.png',crop)[1].tofile(str(destination))
    metadata={'map':map_id,'source':url,'zoom':z,'crop':[x0,y0,x1,y1],'tileBounds':tilebounds,'bounds':bounds,'meters_per_pixel':(tilebounds['maxX']-tilebounds['minX'])*config.get('coordinateMetersPerUnit',100)/size}
    destination.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print(json.dumps(metadata),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--zoom',type=int,default=5);parser.add_argument('--color',action='store_true')
    parser.add_argument('--map',default='ozeti',choices=['ozeti','bakurani','zestafona']);parser.add_argument('--all-styles',action='store_true');args=parser.parse_args()
    for color in ([False,True] if args.all_styles else [args.color]):fetch_map(args.map,args.zoom,color)


if __name__=='__main__':main()
