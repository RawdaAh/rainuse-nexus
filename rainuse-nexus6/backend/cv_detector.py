"""
cv_detector.py — AquaVista CV Pipeline (Render-stable version)
==============================================================

Main stability changes:
1. YOLO is NOT loaded at import time anymore.
2. Only LOCAL model weights are used. No auto-download on startup.
3. Tower detection uses a single zoom level by default instead of trying 17/18/19.
"""

import io
import os
import re
import math
import base64
from datetime import datetime

import requests
import numpy as np
from PIL import Image, ImageDraw

try:
    import cv2
    CV2_OK = True
except Exception:
    CV2_OK = False
    print("[CV] WARNING: OpenCV not available — pip install opencv-python-headless")

try:
    from ultralytics import YOLO as _YOLO_CLS
    YOLO_OK = True
except Exception:
    YOLO_OK = False
    _YOLO_CLS = None

try:
    from shapely.geometry import Polygon
    import pyproj
    from shapely.ops import transform as shapely_transform
    SHAPELY_OK = True
except Exception:
    SHAPELY_OK = False


# ── Paths / model config ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)

# Global lazy-loaded model
_yolo_model = None
_yolo_source = "none"

# Put local weights in backend/ next to this file if you want YOLO enabled.
TOWERSCOUT_WEIGHTS = os.path.join(BASE_DIR, "towerscout.pt")
LOCAL_YOLO_WEIGHTS = [
    TOWERSCOUT_WEIGHTS,                         # best if available
    os.path.join(BASE_DIR, "yolov8n.pt"),      # lighter fallback
    os.path.join(BASE_DIR, "yolov8s.pt"),      # optional fallback
]

# ── Network config ──────────────────────────────────────────────────────────
_HDR = {
    "User-Agent": "Mozilla/5.0 (compatible; AquaVista-RainUSE/1.0)",
    "Referer": "https://grundfos.com",
}

# Safer network timeout: (connect timeout, read timeout)
REQ_TIMEOUT = (8, 20)

# Zoom-level pixel scale at ~35°N (metres per pixel)
ZOOM_MPP = {16: 2.39, 17: 1.19, 18: 0.60, 19: 0.30}


# ══════════════════════════════════════════════════════════════════════════════
# MODEL LOADING
# ══════════════════════════════════════════════════════════════════════════════

def _load_local_yolo_once():
    """
    Lazy-load YOLO only when needed, and only from LOCAL files.
    This avoids auto-downloads and heavy startup work on Render.
    """
    global _yolo_model, _yolo_source

    if _yolo_model is not None:
        return _yolo_model

    if not YOLO_OK:
        _yolo_source = "unavailable"
        return None

    for w in LOCAL_YOLO_WEIGHTS:
        if not os.path.exists(w):
            continue
        try:
            _yolo_model = _YOLO_CLS(w)
            _yolo_source = os.path.basename(w)
            is_towerscout = "towerscout" in _yolo_source.lower()
            print(
                f"[CV] YOLO loaded: {_yolo_source}"
                f"{'  ← PURPOSE-BUILT FOR COOLING TOWERS (best)' if is_towerscout else '  ← local fallback'}"
            )
            return _yolo_model
        except Exception as e:
            print(f"[CV] Failed to load local YOLO weights {w}: {e}")

    print("[CV] No local YOLO weights found. Continuing without YOLO.")
    _yolo_source = "none"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# TILE FETCH
# ══════════════════════════════════════════════════════════════════════════════

def _lat_lng_to_tile(lat, lng, zoom):
    n = 2 ** zoom
    x = int((lng + 180) / 360 * n)
    lr = math.radians(lat)
    y = int((1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n)
    return x, y


def _tile_to_lat_lng(x, y, zoom):
    n = 2 ** zoom
    lng = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lng


def _tile_bounds(cx, cy, zoom, radius):
    nw_lat, nw_lng = _tile_to_lat_lng(cx - radius, cy - radius, zoom)
    se_lat, se_lng = _tile_to_lat_lng(cx + radius + 1, cy + radius + 1, zoom)
    return {"north": nw_lat, "south": se_lat, "west": nw_lng, "east": se_lng}


def fetch_tiles(lat, lng, zoom=17, radius=1):
    cx, cy = _lat_lng_to_tile(lat, lng, zoom)
    ts, g = 256, 2 * radius + 1
    canvas = Image.new("RGB", (g * ts, g * ts), (28, 38, 50))

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            url = (
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                f"World_Imagery/MapServer/tile/{zoom}/{cy + dy}/{cx + dx}"
            )
            try:
                r = requests.get(url, headers=_HDR, timeout=REQ_TIMEOUT)
                r.raise_for_status()
                canvas.paste(
                    Image.open(io.BytesIO(r.content)).convert("RGB"),
                    ((dx + radius) * ts, (dy + radius) * ts),
                )
            except Exception:
                pass

    return canvas, _tile_bounds(cx, cy, zoom, radius)


def _geo_to_px(lon, lat, bounds, w, h):
    x = (lon - bounds["west"]) / (bounds["east"] - bounds["west"]) * w
    y = (bounds["north"] - lat) / (bounds["north"] - bounds["south"]) * h
    return float(x), float(y)


def _sharpness(img_pil):
    if not CV2_OK:
        return 0.0
    gray = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _fetch_best_zoom(lat, lng, zooms=(17, 18, 19), radius=1):
    """
    Kept for optional future use, but NOT used in detect_towers() by default anymore.
    """
    best = (None, None, 17, -1.0)
    for z in zooms:
        img, bounds = fetch_tiles(lat, lng, zoom=z, radius=radius)
        sc = _sharpness(img)
        if sc > best[3]:
            best = (img, bounds, z, sc)
    return best


# ══════════════════════════════════════════════════════════════════════════════
# OSM FOOTPRINT
# ══════════════════════════════════════════════════════════════════════════════

def get_osm_footprint(lat, lng):
    query = f"""[out:json];
    (way["building"](around:150,{lat},{lng});
     relation["building"](around:150,{lat},{lng}););
    out geom;"""
    try:
        r = requests.get(
            "https://overpass-api.de/api/interpreter",
            params={"data": query},
            headers=_HDR,
            timeout=REQ_TIMEOUT,
        )
        r.raise_for_status()
        elements = r.json().get("elements", [])
        if not elements:
            return None, 0.0

        el = elements[0]
        coords = [(pt["lon"], pt["lat"]) for pt in el["geometry"]]

        if SHAPELY_OK:
            poly = Polygon(coords)
            proj = pyproj.Transformer.from_crs(
                "EPSG:4326", "EPSG:3857", always_xy=True
            ).transform
            area_sqft = shapely_transform(proj, poly).area * 10.7639
        else:
            R = 6_371_000
            lats = [math.radians(c[1]) for c in coords]
            lons = [math.radians(c[0]) for c in coords]
            a = 0.0
            for i in range(len(lats)):
                j = (i + 1) % len(lats)
                a += (lons[j] - lons[i]) * (
                    2 + math.sin(lats[i]) + math.sin(lats[j])
                )
            area_sqft = abs(a * R * R / 2.0) * 10.7639

        return coords, area_sqft
    except Exception:
        return None, 0.0


# ══════════════════════════════════════════════════════════════════════════════
# ROOF DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_roof(img_pil, building, bounds):
    coords, area = get_osm_footprint(building["lat"], building["lng"])
    if not coords:
        return {
            "detected": False,
            "area_sqft": 0,
            "confidence": 0.0,
            "over_100k": False,
            "method": "no_osm_footprint",
        }

    w, h = img_pil.size
    poly_px = [_geo_to_px(lon, lat, bounds, w, h) for lon, lat in coords]
    xs = [p[0] for p in poly_px]
    ys = [p[1] for p in poly_px]
    bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]

    if not CV2_OK:
        return {
            "detected": True,
            "bbox_px": bbox,
            "polygon_px": poly_px,
            "area_sqft": round(area),
            "confidence": 0.72,
            "over_100k": area >= 100_000,
            "method": "osm_prior_only",
        }

    img_np = np.array(img_pil)
    x0, y0, x1, y1 = bbox
    pad = 20
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(w, x1 + pad), min(h, y1 + pad)
    crop = img_np[cy0:cy1, cx0:cx1]

    if crop.size == 0:
        return {
            "detected": True,
            "bbox_px": bbox,
            "polygon_px": poly_px,
            "area_sqft": round(area),
            "confidence": 0.70,
            "over_100k": area >= 100_000,
            "method": "osm_prior_crop_empty",
        }

    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    not_green = cv2.bitwise_not(cv2.inRange(hsv, (30, 25, 25), (95, 255, 255)))
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.bitwise_and(thresh, not_green)

    k = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(
        cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2),
        cv2.MORPH_OPEN,
        k,
        iterations=1,
    )
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_cnt, best_sc = None, -1.0
    for c in cnts:
        ap = cv2.contourArea(c)
        if ap < 300:
            continue
        rx, ry, rw, rh = cv2.boundingRect(c)
        fr = ap / max(rw * rh, 1)
        cxc, cyc = rx + rw / 2, ry + rh / 2
        dist = ((cxc - crop.shape[1] / 2) ** 2 + (cyc - crop.shape[0] / 2) ** 2) ** 0.5
        s = ap * (0.5 + fr) - 2.0 * dist
        if s > best_sc:
            best_sc, best_cnt = s, c

    if best_cnt is None:
        return {
            "detected": True,
            "bbox_px": bbox,
            "polygon_px": poly_px,
            "area_sqft": round(area),
            "confidence": 0.74,
            "over_100k": area >= 100_000,
            "method": "osm_prior_cv_no_contour",
        }

    prior_mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(prior_mask, [np.array(poly_px, dtype=np.int32)], 255)

    local_m = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(local_m, [best_cnt], -1, 255, thickness=-1)

    full_m = np.zeros((h, w), np.uint8)
    full_m[cy0:cy1, cx0:cx1] = local_m

    ratio = np.count_nonzero(full_m) / max(np.count_nonzero(prior_mask), 1)
    ratio = max(0.60, min(1.40, ratio))
    refined_area = area * ratio

    overlap = np.count_nonzero(cv2.bitwise_and(prior_mask, full_m)) / max(
        np.count_nonzero(full_m), 1
    )
    conf = min(0.95, 0.55 + 0.30 * overlap + 0.10 * ratio)

    ys2, xs2 = np.where(full_m > 0)
    rbbox = [int(xs2.min()), int(ys2.min()), int(xs2.max()), int(xs2.max())] if len(xs2) else bbox

    return {
        "detected": True,
        "bbox_px": rbbox,
        "polygon_px": poly_px,
        "area_sqft": round(refined_area),
        "confidence": round(conf, 3),
        "over_100k": refined_area >= 100_000,
        "method": "osm_prior_plus_cv_refinement",
    }


# ══════════════════════════════════════════════════════════════════════════════
# COOLING TOWER DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _build_search_mask(img_pil, bounds, roof_data, buffer_px=80):
    """Restrict search to roof area + generous buffer."""
    w, h = img_pil.size
    mask = np.zeros((h, w), np.uint8)

    poly_px = roof_data.get("polygon_px")
    if poly_px and len(poly_px) >= 3:
        pts = np.array(poly_px, dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)
    else:
        bx0, by0, bx1, by1 = roof_data.get("bbox_px", [w // 6, h // 6, w * 5 // 6, h * 5 // 6])
        cv2.rectangle(mask, (bx0, by0), (bx1, by1), 255, -1)

    k = np.ones((buffer_px, buffer_px), np.uint8)
    return cv2.dilate(mask, k, iterations=1)


def _clahe_enhance(img_rgb):
    """CLAHE contrast enhancement — improves dark cluster visibility."""
    bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(l)
    bgr2 = cv2.cvtColor(cv2.merge((l2, a, b)), cv2.COLOR_LAB2BGR)
    return cv2.cvtColor(bgr2, cv2.COLOR_BGR2RGB)


def _dark_cluster_score(gray_patch):
    if gray_patch.size == 0:
        return 0.0
    mean_val = float(gray_patch.mean())
    score = max(0.0, min(1.0, (150.0 - mean_val) / 100.0))
    return score


def _fan_grid_score(gray_patch, min_circles=2):
    if gray_patch.size == 0 or not CV2_OK:
        return 0.0, 0

    H, W = gray_patch.shape
    if H < 15 or W < 15:
        return 0.0, 0

    patch_eq = cv2.equalizeHist(gray_patch)
    min_r = max(2, int(H * 0.08))
    max_r = max(min_r + 2, int(H * 0.35))

    blur = cv2.GaussianBlur(patch_eq, (5, 5), 1)
    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min_r * 2,
        param1=50,
        param2=18,
        minRadius=min_r,
        maxRadius=max_r,
    )

    n_circles = 0 if circles is None else len(circles[0])
    score = min(1.0, n_circles / 4.0)
    return score, n_circles


def _detect_dark_rectangles(gray, enhanced_gray, search_mask, zoom):
    mpp = ZOOM_MPP.get(zoom, 1.19)
    min_side_px = max(6, int(4.0 / mpp))
    max_side_px = min(400, int(80.0 / mpp))

    candidates = []

    if search_mask is not None:
        gray_search = cv2.bitwise_and(gray, gray, mask=search_mask)
    else:
        gray_search = gray

    dark_abs = cv2.inRange(gray_search, 0, 125)
    dark_adapt = cv2.adaptiveThreshold(
        gray_search,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=51,
        C=15,
    )
    dark_combined = cv2.bitwise_and(dark_abs, dark_adapt)

    k_close = np.ones((max(3, min_side_px // 3), max(3, min_side_px // 3)), np.uint8)
    dark_closed = cv2.morphologyEx(dark_combined, cv2.MORPH_CLOSE, k_close, iterations=2)

    k_open = np.ones((3, 3), np.uint8)
    dark_clean = cv2.morphologyEx(dark_closed, cv2.MORPH_OPEN, k_open, iterations=1)

    cnts, _ = cv2.findContours(dark_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for c in cnts:
        area_px = cv2.contourArea(c)
        if area_px < (min_side_px ** 2) * 0.5:
            continue
        if area_px > (max_side_px ** 2) * 3.0:
            continue

        x, y, bw, bh = cv2.boundingRect(c)
        if bw < min_side_px or bh < min_side_px:
            continue
        if bw > max_side_px * 1.5 or bh > max_side_px * 1.5:
            continue

        aspect = bw / max(bh, 1)
        if not (0.25 <= aspect <= 4.0):
            continue

        cx_c, cy_c = x + bw // 2, y + bh // 2
        r_equiv = int(math.sqrt(area_px / math.pi))

        patch = gray[y:y + bh, x:x + bw]
        if patch.size == 0:
            continue

        darkness = max(0.0, min(1.0, (140.0 - float(patch.mean())) / 90.0))
        if darkness < 0.1:
            continue

        fan_score, n_fans = _fan_grid_score(patch)
        compactness = min(aspect, 1.0 / aspect)

        conf = (
            0.50 * darkness
            + 0.25 * fan_score
            + 0.15 * compactness
            + 0.10 * min(1.0, area_px / (min_side_px ** 2 * 4))
        )
        conf = min(0.88, max(0.0, conf))

        if conf < 0.18:
            continue

        candidates.append(
            {
                "cx": cx_c,
                "cy": cy_c,
                "r": r_equiv,
                "bbox_px": [x, y, x + bw, y + bh],
                "darkness": round(darkness, 3),
                "fan_score": round(fan_score, 3),
                "n_fans": n_fans,
                "confidence": round(conf, 3),
                "detector": "dark_rect_fan_grid",
            }
        )

    return candidates


def _yolo_detector(img_pil, offset_x, offset_y, is_towerscout=False):
    if _yolo_model is None or not CV2_OK:
        return []

    img_np = np.array(img_pil)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    results = _yolo_model(img_np, conf=0.18, imgsz=1024, verbose=False)
    candidates = []

    for r in results:
        if not hasattr(r, "boxes") or r.boxes is None:
            continue

        for box in r.boxes:
            b = box.xyxy[0].cpu().numpy()
            conf_yolo = float(box.conf[0])
            bx0, by0, bx1, by1 = int(b[0]), int(b[1]), int(b[2]), int(b[3])
            bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)
            area = bw * bh
            aspect = bw / float(bh)

            if area < 50 or area > 80_000:
                continue
            if not (0.20 <= aspect <= 5.0):
                continue

            cx_c = (bx0 + bx1) // 2
            cy_c = (by0 + by1) // 2
            r_eq = int(math.sqrt(area / math.pi))

            if is_towerscout:
                conf = min(0.92, conf_yolo)
                detector_tag = "towerscout_yolo"
            else:
                if 0 <= by0 < by1 <= gray.shape[0] and 0 <= bx0 < bx1 <= gray.shape[1]:
                    patch = gray[by0:by1, bx0:bx1]
                    darkness = max(0.0, min(1.0, (140.0 - float(patch.mean())) / 90.0))
                    if darkness < 0.12:
                        continue
                    fan_sc, _ = _fan_grid_score(patch)
                    conf = min(0.80, conf_yolo * 0.40 + darkness * 0.40 + fan_sc * 0.20)
                else:
                    conf = conf_yolo * 0.35
                detector_tag = "generic_yolo_dark_validated"

            if conf < 0.15:
                continue

            candidates.append(
                {
                    "cx": cx_c + offset_x,
                    "cy": cy_c + offset_y,
                    "r": r_eq,
                    "bbox_px": [bx0 + offset_x, by0 + offset_y, bx1 + offset_x, by1 + offset_y],
                    "confidence": round(conf, 3),
                    "detector": detector_tag,
                }
            )

    return candidates


def _iou(a, b):
    ax0, ay0, ax1, ay1 = a.get("bbox_px", [0, 0, 0, 0])
    bx0, by0, bx1, by1 = b.get("bbox_px", [0, 0, 0, 0])
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    ua = max(1, (ax1 - ax0) * (ay1 - ay0))
    ub = max(1, (bx1 - bx0) * (by1 - by0))
    return inter / float(ua + ub - inter)


def _deduplicate(candidates, iou_thresh=0.40):
    kept = []
    for c in sorted(candidates, key=lambda x: x["confidence"], reverse=True):
        if not any(_iou(c, k) > iou_thresh for k in kept):
            kept.append(c)
    return kept


def detect_towers(building, roof_data):
    """
    Tower detection with:
    - lazy local-only YOLO load
    - single zoom fetch for lower network/CPU load
    """
    _load_local_yolo_once()

    if not roof_data.get("detected"):
        return {
            "present": False,
            "count": 0,
            "towers": [],
            "confidence": 0.0,
            "method": "roof_not_detected",
        }

    if not CV2_OK:
        return {
            "present": False,
            "count": 0,
            "towers": [],
            "confidence": 0.0,
            "method": "cv2_unavailable",
        }

    # Single zoom instead of trying 17/18/19 for every building
    zoom = int(building.get("tower_zoom", 18))
    img_pil, bounds = fetch_tiles(building["lat"], building["lng"], zoom=zoom, radius=1)
    sharpness = _sharpness(img_pil)

    img_np = np.array(img_pil)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    w, h = img_pil.size

    search_mask = _build_search_mask(img_pil, bounds, roof_data, buffer_px=80)
    enhanced_np = _clahe_enhance(img_np)
    enhanced_gray = cv2.cvtColor(enhanced_np, cv2.COLOR_RGB2GRAY)

    dark_candidates = _detect_dark_rectangles(gray, enhanced_gray, search_mask, zoom)
    print(f"  [CT] Dark-rect: {len(dark_candidates)} candidates  zoom={zoom}")

    yolo_candidates = []
    if _yolo_model is not None:
        sy, sx = np.where(search_mask > 0)
        if len(sy) > 0:
            x0c, y0c = max(0, int(sx.min())), max(0, int(sy.min()))
            x1c, y1c = min(w, int(sx.max())), min(h, int(sy.max()))
            crop_pil = Image.fromarray(img_np[y0c:y1c, x0c:x1c])
            if crop_pil.size[0] > 20 and crop_pil.size[1] > 20:
                is_ts = "towerscout" in _yolo_source.lower()
                yolo_candidates = _yolo_detector(crop_pil, x0c, y0c, is_towerscout=is_ts)
        print(f"  [CT] YOLO ({_yolo_source}): {len(yolo_candidates)} candidates")
    else:
        print("  [CT] YOLO disabled (no local weights found)")

    all_candidates = dark_candidates + yolo_candidates
    deduped = _deduplicate(all_candidates, iou_thresh=0.40)
    deduped = [c for c in deduped if c["confidence"] >= 0.20]
    deduped = deduped[:20]

    print(f"  [CT] Final: {len(deduped)} towers (dedup+thresh)")

    if not deduped:
        return {
            "present": False,
            "count": 0,
            "towers": [],
            "confidence": 0.0,
            "method": "no_dark_clusters_found_on_roof",
            "note": "If building has cooling towers, add local TowerScout weights as towerscout.pt",
            "zoom_used": zoom,
            "sharpness": round(sharpness, 1),
        }

    confs = [d["confidence"] for d in deduped]
    n = len(confs)
    final_conf = min(
        0.95,
        confs[0] * 0.50
        + (confs[1] if n > 1 else confs[0]) * 0.30
        + (confs[2] if n > 2 else confs[0]) * 0.20
        + min(0.05, n * 0.01),
    )

    towers_out = []
    for d in deduped:
        cx, cy = d["cx"], d["cy"]
        bbox = d.get("bbox_px", [cx - 10, cy - 10, cx + 10, cy + 10])
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        r = int(math.sqrt(bw * bh / math.pi)) if bw * bh > 0 else d.get("r", 10)
        towers_out.append(
            {
                "center_px": [cx, cy],
                "radius_px": r,
                "bbox_px": bbox,
                "confidence": d["confidence"],
                "n_fans_detected": d.get("n_fans", 0),
                "detector": d["detector"],
            }
        )

    return {
        "present": True,
        "count": len(towers_out),
        "towers": towers_out,
        "confidence": round(final_conf, 3),
        "method": "dark_cluster_fan_grid_yolo_fusion",
        "detectors": list({d["detector"] for d in deduped}),
        "zoom_used": zoom,
        "sharpness": round(sharpness, 1),
        "model_note": (
            "For best results, add local TowerScout weights as towerscout.pt. "
            "Generic YOLO is optional and local-only in this version."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# ANNOTATION
# ══════════════════════════════════════════════════════════════════════════════

def annotate(img_pil, roof, towers, building):
    out = img_pil.copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size

    if roof.get("polygon_px"):
        pts = [(int(x), int(y)) for x, y in roof["polygon_px"]]
        if len(pts) >= 3:
            draw.polygon(pts, outline=(0, 229, 180))

    if roof.get("bbox_px"):
        x0, y0, x1, y1 = roof["bbox_px"]
        for t in range(2):
            draw.rectangle([x0 - t, y0 - t, x1 + t, y1 + t], outline=(0, 229, 180))
        lbl = (
            f"ROOF  {roof.get('area_sqft', 0):,} ft²  "
            f"CONF {roof.get('confidence', 0) * 100:.0f}%  "
            f"{'✓>100K' if roof.get('over_100k') else '✗<100K'}"
        )
        draw.rectangle([x0, max(0, y0 - 18), x0 + len(lbl) * 6 + 4, y0], fill=(0, 229, 180))
        draw.text((x0 + 2, max(0, y0 - 17)), lbl, fill=(0, 0, 0))

    for i, tw in enumerate(towers.get("towers", [])):
        x0, y0, x1, y1 = tw.get("bbox_px", [0, 0, 0, 0])
        if x1 <= 0 or y1 <= 0 or x0 >= w or y0 >= h:
            continue
        for t in range(2):
            draw.rectangle([x0 - t, y0 - t, x1 + t, y1 + t], outline=(245, 158, 11))
        fans = tw.get("n_fans_detected", 0)
        det = tw.get("detector", "")[:6]
        lbl = f"CT-{i+1}  {tw['confidence']*100:.0f}%  fans:{fans}  [{det}]"
        draw.text((x0, max(0, y0 - 15)), lbl, fill=(245, 158, 11))

    status = f"TOWERS: {towers.get('count', 0)} detected  CONF {towers.get('confidence', 0) * 100:.0f}%"
    draw.rectangle([0, 0, w, 20], fill=(13, 43, 26))
    draw.text((6, 3), status, fill=(212, 243, 220))

    footer = f"AquaVista · ESRI Satellite · {building.get('address', '?')}"
    draw.rectangle([0, h - 18, w, h], fill=(13, 43, 26))
    draw.text((4, h - 15), footer, fill=(116, 198, 157))

    return out


# ══════════════════════════════════════════════════════════════════════════════
# FILE SAVE
# ══════════════════════════════════════════════════════════════════════════════

def _safe_slug(t):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", (t or "x").strip().lower())).strip("_") or "x"


def _save_images(clean, annotated, building):
    base = os.path.join(
        BASE_DIR,
        "saved_cv_images",
        _safe_slug(building.get("state", "")),
        _safe_slug(building.get("city", "")),
    )
    os.makedirs(base, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    n = _safe_slug(building.get("name", "x"))

    cp = os.path.join(base, f"{n}_{stamp}_clean.jpg")
    ap = os.path.join(base, f"{n}_{stamp}_annotated.jpg")

    clean.save(cp, "JPEG", quality=95)
    annotated.save(ap, "JPEG", quality=95)

    return {"clean_path": cp, "annotated_path": ap}


# ══════════════════════════════════════════════════════════════════════════════
# FULL PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(building):
    zoom = int(building.get("zoom", 17))
    print(f"\n[CV] {building.get('name', '?')}")
    print(f"     GPS: {building['lat']:.5f}N  {abs(building['lng']):.5f}W  zoom={zoom}")

    try:
        img_roof, bounds_roof = fetch_tiles(building["lat"], building["lng"], zoom=zoom, radius=1)
    except Exception as e:
        return {"error": f"Tile fetch failed: {e}"}

    print(f"     Image: {img_roof.size[0]}×{img_roof.size[1]}px")

    roof = detect_roof(img_roof, building, bounds_roof)
    print(
        f"     Roof: area={roof.get('area_sqft', 0):,} ft²  "
        f"conf={roof.get('confidence', 0):.0%}  >100K={roof.get('over_100k')}"
    )

    towers = detect_towers(building, roof)
    print(
        f"     Towers: {towers['count']} detected  "
        f"conf={towers.get('confidence', 0):.0%}  method={towers.get('method')}"
    )

    annotated = annotate(img_roof, roof, towers, building)
    saved = _save_images(img_roof, annotated, building)

    b1 = io.BytesIO()
    annotated.save(b1, "JPEG", quality=88)

    return {
        "building_id": building.get("id"),
        "building_name": building.get("name", "?"),
        "building_address": building.get("address", "?"),
        "building_type": building.get("building_type", "?"),
        "lat": building["lat"],
        "lng": building["lng"],
        "tile_bounds": bounds_roof,
        "zoom": zoom,
        "source": "ESRI World Imagery (Maxar/Earthstar Geographics)",
        "image_size": list(img_roof.size),
        "cv_model": {
            "roof": roof.get("method"),
            "towers": towers.get("method"),
            "yolo_weights": _yolo_source,
            "towerscout_note": "Use local towerscout.pt if available",
        },
        "roof": roof,
        "roof_requirement_flag": roof.get("over_100k", False),
        "towers": towers,
        "tower_presence_flag": towers.get("present", False),
        "annotated_b64": base64.b64encode(b1.getvalue()).decode(),
        "saved_files": saved,
    }
