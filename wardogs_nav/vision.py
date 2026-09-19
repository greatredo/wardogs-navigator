"""Image-only localization. No process handles, game hooks or input injection."""
from dataclasses import dataclass
from pathlib import Path
import math
import cv2
import numpy as np


def read_image(path: str | Path):
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片：{path}")
    return image


@dataclass
class Fix:
    x: float = 0
    y: float = 0
    confidence: float = 0
    inliers: int = 0
    error: float = 0
    scale: float = 0
    rotation: float = 0
    heading: float | None = None
    valid: bool = False
    reason: str = "未定位"
    map_id: str | None = None
    generation: int = 0


def feature_mask(image, minimap=True, path_mask=None):
    h, w = image.shape[:2]
    mask = np.full((h, w), 255, np.uint8)
    mask[:5] = mask[-(max(5,int(h*.08)) if minimap else 5):] = 0
    mask[:, :5] = mask[:, -5:] = 0
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # HUD colours and bright lettering / player marker are transient.
    overlay = ((hsv[:, :, 1] > 80) | (hsv[:, :, 2] > 215)).astype(np.uint8)
    overlay = cv2.dilate(overlay, np.ones((7, 7), np.uint8))
    mask[overlay > 0] = 0
    if path_mask and len(path_mask[0])>=2:
        # Mask our last rendered screen-space route as well as its colour. This
        # remains reliable when users choose a nearly transparent path.
        cv2.polylines(mask,[np.int32(path_mask[0])],False,0,max(3,round(path_mask[1])+10))
    return mask


def player_heading(image, anchor):
    """Estimate the white arrow's tip from its concave polygon near the anchor."""
    h, w = image.shape[:2]
    cx, cy = anchor[0] * w, anchor[1] * h
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    binary = ((hsv[:, :, 1] < 50) & (hsv[:, :, 2] > 210)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = [c for c in contours if 12 < cv2.contourArea(c) < w*h*.012]
    if not candidates:
        return None
    def center(c):
        m = cv2.moments(c)
        return np.array([m['m10']/max(m['m00'], 1), m['m01']/max(m['m00'], 1)])
    contour = min(candidates, key=lambda c: np.linalg.norm(center(c) - [cx, cy]))
    origin = center(contour)
    if np.linalg.norm(origin - [cx, cy]) > min(h, w)*.12:
        return None
    try:
        polygon = cv2.approxPolyDP(contour, .025*cv2.arcLength(contour, True), True)
        if len(polygon) < 4:
            return None
        hull = cv2.convexHull(polygon, returnPoints=False)
        if hull is None or len(hull) < 3 or len(hull) >= len(polygon):
            return None
        defects = cv2.convexityDefects(polygon, hull)
    except cv2.error:
        # Touching icons can produce self-intersections or invalid hull indices.
        # Heading is optional: this must not discard a valid terrain match.
        return None
    if defects is None:
        return None
    defect = max(defects.reshape(-1, 4), key=lambda d: d[3])
    notch = polygon[defect[2], 0].astype(float)
    tip = max(polygon[:, 0], key=lambda p: np.linalg.norm(p - notch))
    return math.degrees(math.atan2(tip[0]-origin[0], origin[1]-tip[1])) % 360


class Locator:
    def __init__(self, map_image=None, *, points=None, descriptors=None, map_shape=None):
        cv2.setNumThreads(2)
        self.map_shape=map_shape or map_image.shape[:2]
        self.sift = cv2.SIFT_create(nfeatures=24000, contrastThreshold=.008, edgeThreshold=14)
        if points is None:
            keypoints, descriptors = self.sift.detectAndCompute(cv2.cvtColor(map_image, cv2.COLOR_BGR2GRAY), feature_mask(map_image,minimap=False))
            points=np.float32([p.pt for p in keypoints])
        self.points=np.float32(points);self.descriptors=np.float32(descriptors)
        self.matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=96))
        self.matcher.add([self.descriptors])
        self.matcher.train()
        self.last=None

    @classmethod
    def from_assets(cls,map_id='ozeti'):
        from .maps import map_asset,map_info
        info=map_info(map_id)
        with np.load(map_asset(map_id,'features'),allow_pickle=False) as data:
            return cls(points=data['points'],descriptors=data['descriptors'],map_shape=(info['height'],info['width']))

    def locate(self, image, anchor=(.5, .5), north_up=True, path_mask=None):
        if image is None or min(image.shape[:2]) < 60:
            return Fix(reason="采集区域太小")
        points, desc = self.sift.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), feature_mask(image,path_mask=path_mask))
        if desc is None or len(desc) < 8:
            return Fix(reason="缺少可匹配地形，请检查截图区域")
        # Track locally after an accepted fix, while retaining global recovery.
        if self.last:
            radius=max(65,max(image.shape[:2])*self.last.scale*1.5)
            selected=np.where(np.sum((self.points-[self.last.x,self.last.y])**2,axis=1)<radius**2)[0]
            if len(selected)>=20:
                matcher=cv2.FlannBasedMatcher(dict(algorithm=1,trees=3),dict(checks=64))
                matcher.add([self.descriptors[selected]]);matcher.train()
                fix=self._match(image,points,desc,matcher,self.points[selected],anchor,north_up)
                if fix.valid:self.last=fix;return fix
        fix=self._match(image,points,desc,self.matcher,self.points,anchor,north_up)
        self.last=fix if fix.valid else None
        return fix

    def _match(self,image,points,desc,matcher,reference,anchor,north_up):
        pairs = matcher.knnMatch(desc, k=2)
        good = [m for pair in pairs if len(pair) == 2 for m, n in [pair] if m.distance < .76*n.distance]
        if len(good) < 8:
            return Fix(reason=f"地形匹配不足（{len(good)}）")
        src = np.float32([points[m.queryIdx].pt for m in good])
        dst = np.float32([reference[m.trainIdx] for m in good])
        mat, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.5, maxIters=5000, confidence=.995)
        if mat is None:
            return Fix(reason="无法建立稳定的地图对应关系")
        valid = mask.ravel().astype(bool)
        count = int(valid.sum())
        scale = float(np.linalg.norm(mat[:, 0]))
        rotation = math.degrees(math.atan2(mat[1, 0], mat[0, 0]))
        residual = np.linalg.norm(src @ mat[:, :2].T + mat[:, 2] - dst, axis=1)
        error = float(np.median(residual[valid]))
        h, w = image.shape[:2]
        x, y = mat @ [anchor[0]*w, anchor[1]*h, 1]
        spread = float(cv2.contourArea(cv2.convexHull(src[valid]))) / (w*h) if count >= 3 else 0
        confidence = min(1., count/24) * min(1., (count/len(good))/.55) * min(1., spread/.1)
        ok = count >= 8 and confidence >= .35 and error < min(2,2.5*scale) and .025 < scale < 6 and 0 <= x < self.map_shape[1] and 0 <= y < self.map_shape[0]
        if north_up and abs(rotation) > 6:
            ok = False
        heading = player_heading(image, anchor)
        if heading is not None:
            heading = (heading + rotation) % 360
        return Fix(float(x), float(y), confidence, count, error, scale, rotation, heading, bool(ok), "定位成功" if ok else "匹配不可靠，暂停播报")
