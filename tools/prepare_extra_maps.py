"""Prepare the two additional public maps without altering OZETI coordinates."""
from pathlib import Path
import argparse,json,sys
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wardogs_nav.vision import read_image
from wardogs_nav.model import atomic_json


def prepare(map_id,stage):
    folder=ROOT/'research/maps'/map_id;assets=ROOT/'assets/maps'/map_id
    assets.mkdir(parents=True,exist_ok=True);cv2.setNumThreads(2)
    gray=read_image(folder/'clean-grayscale-z5.png')
    scale=2048/max(gray.shape[:2])
    if stage in ('images','all'):
        color=read_image(folder/'clean-color-z5.png')
        image=cv2.resize(gray,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
        cv2.imencode('.png',image)[1].tofile(str(assets/'map.png'))
        for name,source in [('gray-preview',gray),('color-preview',color)]:
            preview=cv2.resize(source,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
            cv2.imencode('.png',preview)[1].tofile(str(folder/(name+'.png')))
        metadata=json.loads((folder/'clean-grayscale-z5.json').read_text(encoding='utf-8'))
        metadata.update(upstream='https://github.com/apollyon-sys/wardogs-calculator',
                        reference='Public grayscale z5 tiles, cropped to configured play area',
                        reference_to_map=[[scale,0,0],[0,scale,0],[0,0,1]],
                        reference_meters_per_pixel=metadata['meters_per_pixel'],
                        meters_per_pixel=metadata['meters_per_pixel']/scale,dataset_revision=1)
        x,y=gray.shape[1]//2,gray.shape[0]//2
        crop=gray[y-228:y+228,x-256:x+256]
        crop=cv2.resize(crop,(340,303),interpolation=cv2.INTER_AREA)
        cv2.imencode('.png',crop)[1].tofile(str(assets/'reference-crop.png'))
        metadata['reference_crop']={'point':[x*scale,y*scale],'image':'reference-crop.png','type':'public_image_crop_not_game_capture'}
        atomic_json(assets/'source.json',metadata)
        registry=json.loads((ROOT/'assets/maps.json').read_text(encoding='utf-8'))
        info=next(m for m in registry if m['id']==map_id);info.update(width=image.shape[1],height=image.shape[0])
        atomic_json(ROOT/'assets/maps.json',registry)
        if not (assets/'project.json').exists():
            data=dict(schema=1,map=map_id,meters_per_pixel=metadata['meters_per_pixel'],road_data_revision=1,
                      calibration={'source':'公开地图瓦片边界与裁剪比例','status':'公开地图比例尺；可用游戏内两点复核'},
                      roads=[],notes=[],avoid=[],waypoints=[],destinations=[],destination=None,
                      roundtrip=False,policy={'allowed':['major','minor'],'confirmed_only':False},route_library=[])
            atomic_json(assets/'project.json',data)
        print(map_id,'display',image.shape[:2],'meters_per_pixel',metadata['meters_per_pixel'],flush=True)
    if stage in ('features','all'):
        sift=cv2.SIFT_create(nfeatures=180000,contrastThreshold=.008,edgeThreshold=14)
        kp,desc=sift.detectAndCompute(cv2.cvtColor(gray,cv2.COLOR_BGR2GRAY),None)
        points=np.float32([p.pt for p in kp])*scale
        np.savez_compressed(assets/'features.npz',points=points,descriptors=desc.astype(np.uint8))
        print(map_id,'features',len(points),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--map',choices=['bakurani','zestafona'],required=True)
    parser.add_argument('--stage',choices=['images','features','all'],default='all');args=parser.parse_args()
    prepare(args.map,args.stage)
