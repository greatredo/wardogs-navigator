"""Align clean public terrain to the existing project coordinate frame."""
from pathlib import Path
import sys,json
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wardogs_nav.vision import read_image

old=read_image(ROOT/'assets/ozeti.png');clean=read_image(ROOT/'research/clean-grayscale-z5.png')
# Keep the published coordinate transform; no original player screenshots are required.
report=json.loads((ROOT/'assets/map-source.json').read_text(encoding='utf-8'))
matrix=np.array(report['reference_to_map'])
display=cv2.warpPerspective(clean,matrix,(old.shape[1],old.shape[0]),flags=cv2.INTER_AREA)
cv2.imencode('.png',display)[1].tofile(str(ROOT/'research/clean-aligned.png'))
(ROOT/'research/clean-registration.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
