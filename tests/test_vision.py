import cv2
import numpy as np
import pytest
from wardogs_nav.vision import Locator,read_image
from wardogs_nav.model import asset_path

def minimap(center=(505,1245),span=136):
    """Public map crop with a synthetic arrow; contains no player capture."""
    terrain=read_image(asset_path('ozeti.png'))
    x,y=(round(v) for v in center);half=span//2
    image=cv2.resize(terrain[y-half:y+half,x-half:x+half],(340,340))
    angle=np.deg2rad(50);rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    arrow=np.array([[0,-12],[8,10],[0,5],[-8,10]])@rotation.T+[170,170]
    cv2.fillPoly(image,[np.int32(np.round(arrow))],(255,255,255))
    return image


@pytest.fixture(scope='module')
def locator():return Locator.from_assets()


def test_public_minimap_matches_south_base(locator):
    fix=locator.locate(minimap())
    assert fix.valid and fix.inliers>=20
    assert abs(fix.x-505)<2 and abs(fix.y-1245)<2
    assert 35<fix.heading<65


@pytest.mark.parametrize('span,expected',[(80,(504,1246)),(96,(499,1251)),(120,(504,1247))])
def test_public_crops_at_different_zoom_levels(locator,span,expected):
    fix=locator.locate(minimap(expected,span))
    assert fix.valid and fix.inliers>=8
    assert (fix.x,fix.y)==pytest.approx(expected,abs=2)


def test_dpi_scaling_and_rotation(locator):
    im=minimap()
    scaled=locator.locate(cv2.resize(im,None,fx=1.25,fy=1.25))
    assert scaled.valid and abs(scaled.x-505)<2
    rotated=cv2.rotate(im,cv2.ROTATE_90_CLOCKWISE)
    assert not locator.locate(rotated,north_up=True).valid
    fix=locator.locate(rotated,north_up=False)
    assert fix.valid and abs(fix.x-505)<2 and 35<fix.heading<65


def test_blank_and_unrelated_images_are_rejected(locator):
    assert not locator.locate(np.zeros((303,340,3),np.uint8)).valid
    rng=np.random.default_rng(1)
    assert not locator.locate(rng.integers(0,255,(303,340,3),dtype=np.uint8)).valid


def test_player_anchor_is_respected(locator):
    im=minimap();a=locator.locate(im);b=locator.locate(im,anchor=(.6,.5))
    assert b.valid and abs((b.x-a.x)-13.6)<1


def test_southern_map_edge_is_not_masked_as_minimap_hud(locator):
    im=read_image(asset_path('ozeti.png'))
    query=cv2.resize(im[1320:1446,1150:1300],None,fx=2,fy=2)
    fix=locator.locate(query)
    assert fix.valid and abs(fix.x-1225)<2 and abs(fix.y-1383)<2
