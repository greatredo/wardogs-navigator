"""Precompute public-map image features so startup needs no full-map extraction."""
from pathlib import Path
import json,sys,time
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wardogs_nav.vision import read_image
cv2.setNumThreads(2)
image=read_image(ROOT/'research/clean-grayscale-z5.png')
matrix=np.array(json.loads((ROOT/'research/clean-registration.json').read_text())['reference_to_map'])
sift=cv2.SIFT_create(nfeatures=180000,contrastThreshold=.008,edgeThreshold=14)
kp,desc=sift.detectAndCompute(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),None)
points=np.float32([p.pt for p in kp]);points=points@matrix[:2,:2].T+matrix[:2,2]
np.savez_compressed(ROOT/'assets/ozeti-features.npz',points=np.float32(points),descriptors=desc.astype(np.uint8))
print('cached',len(points),'features')
