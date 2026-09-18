"""Create a public-terrain crop for diagnostics, without player screenshots."""
from pathlib import Path
import sys
import cv2

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from wardogs_nav.vision import read_image


def main():
    terrain=read_image(ROOT/'assets/ozeti.png')
    # Centre (505, 1245), within the existing southern road network.
    sample=cv2.resize(terrain[1185:1305,437:573],None,fx=2.5,fy=2.5)
    destination=ROOT/'assets/sample_minimap.png'
    cv2.imencode('.png',sample)[1].tofile(str(destination))
    print(destination)


if __name__=='__main__':main()
