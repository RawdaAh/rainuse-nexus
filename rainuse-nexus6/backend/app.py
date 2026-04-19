"""
app.py — RainUSE Nexus Flask Backend
====================================

Updated behavior:
1. /api/scan discovers candidates in a state.
2. Each candidate is CV-screened once during scan.
3. CV results are cached in _cv_cache by osm_id.
4. /api/cv/<osm_id> returns cached scan-time CV only.
   It does NOT rerun live CV on open anymore.
"""

import sys
import os
import json
import threading

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request, Response, stream_with_context
from flask_cors import CORS

from scanner import scan_state, STATE_BBOX
from score_engine import (
    calculate_viability,
    harvest_gallons_per_year,
    annual_savings_usd,
    payback_years,
)

try:
    from cv_detector import run_pipeline
    CV_AVAILABLE = True
except Exception as e:
    CV_AVAILABLE = False
    print(f"  WARNING: CV detector not available: {e}")

app = Flask(__name__)
CORS(app)

_scan_cache = {}   # cache_key -> raw discovered buildings
_cv_cache   = {}   # osm_id -> cached CV result from scan


# ── helpers ────────────────────────────────────────────────────────────────

def _normalize_osm_id(value):
    return str(value).replace("osm_", "").strip()


def _cache_cv_result(osm_id, building, cv_result, score_result):
    """
    Store the scan-time CV result so building detail pages can use it later
    without rerunning live CV.
    """
    cache_key = _normalize_osm_id(osm_id)

    payload = {
        "building_id": cv_result.get("building_id", building.get("id")),
        "building_name": cv_result.get("building_name", building.get("name", "?")),
        "building_address": cv_result.get("building_address", building.get("address", "?")),
        "building_type": cv_result.get("building_type", building.get("building_type", "?")),
        "lat": cv_result.get("lat", building.get("lat")),
        "lng": cv_result.get("lng", building.get("lng")),
        "tile_bounds": cv_result.get("tile_bounds"),
        "zoom": cv_result.get("zoom", building.get("zoom")),
        "source": cv_result.get("source"),
        "image_size": cv_result.get("image_size"),
        "cv_model": cv_result.get("cv_model"),
        "roof": cv_result.get("roof"),
        "roof_requirement_flag": cv_result.get("roof_requirement_flag", False),
        "towers": cv_result.get("towers"),
        "tower_presence_flag": cv_result.get("tower_presence_flag", False),
        "annotated_b64": cv_result.get("annotated_b64"),
        "clean_b64": cv_result.get("clean_b64"),
        "saved_files": cv_result.get("saved_files"),
        "viability_score": score_result,
        "cached_from_scan": True,
    }

    _cv_cache[cache_key] = payload


# ── /api/health ───────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "cv_available": CV_AVAILABLE,
        "states_available": list(STATE_BBOX.keys()),
        "discovery_method": "Overpass API (OpenStreetMap) — real-time discovery",
        "cv_model": "Scan-time cached CV pipeline",
        "satellite_source": "ESRI World Imagery (Maxar / Earthstar Geographics)",
        "harvest_formula": "sqft × rainfall_in × 0.623 × 0.85  [FEMP / ARCSA]",
        "address_source": "Nominatim (OpenStreetMap) reverse geocoding",
        "financial_source": "worldpopulationreview.com | UNC EFC | TCEQ",
    })


# ── /api/states ───────────────────────────────────────────────────────────

@app.route("/api/states")
def api_states():
    from score_engine import STATE_FINANCIAL
    return jsonify(STATE_FINANCIAL)


# ── /api/scan ─────────────────────────────────────────────────────────────

@app.route("/api/scan", methods=["POST"])
def api_scan():
    body = request.get_json(force=True) or {}
    state = body.get("state")
    if not state:
        return jsonify({"error": "Missing required field: state"}), 400

    candidate_min_sqft = int(body.get("candidate_min_sqft", 60_000))
    final_min_sqft = int(body.get("final_min_sqft", 100_000))
    max_res = int(body.get("max_results", 20))

    if state not in STATE_BBOX:
        return jsonify({"error": f"State '{state}' not supported"}), 400

    cache_key = f"{state}_{candidate_min_sqft}_{final_min_sqft}_{max_res}"

    try:
        # Use raw candidate cache only for discovery, but always rebuild screened results
        # from those raw candidates so the response stays consistent with current logic.
        if cache_key in _scan_cache:
            buildings = _scan_cache[cache_key]
            cached_flag = True
        else:
            buildings = scan_state(state, min_sqft=candidate_min_sqft, max_results=max_res)
            _scan_cache[cache_key] = buildings
            cached_flag = False

        screened = [_cv_screen_and_score(b) for b in buildings]
        screened = [b for b in screened if b.get("roof_sqft", 0) >= final_min_sqft]
        screened.sort(key=lambda x: x["score"]["viability_score"], reverse=True)

        return jsonify({
            "state": state,
            "candidate_min_sqft": candidate_min_sqft,
            "final_min_sqft": final_min_sqft,
            "count": len(screened),
            "buildings": screened,
            "cached": cached_flag,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /api/scan/stream ──────────────────────────────────────────────────────

@app.route("/api/scan/stream")
def api_scan_stream():
    state = request.args.get("state")
    if not state:
        return jsonify({"error": "Missing required query param: state"}), 400

    candidate_min_sqft = int(request.args.get("candidate_min_sqft", 60_000))
    final_min_sqft = int(request.args.get("final_min_sqft", 100_000))
    max_res = int(request.args.get("max_results", 15))

    if state not in STATE_BBOX:
        return jsonify({"error": f"State '{state}' not supported"}), 400

    def generate():
        buildings_found = []

        try:
            for b in _stream_scan(state, candidate_min_sqft, max_res):
                screened = _cv_screen_and_score(b)

                if screened.get("roof_sqft", 0) < final_min_sqft:
                    continue

                buildings_found.append(screened)
                yield f"data: {json.dumps({'type':'building','building':screened})}\n\n"

            yield f"data: {json.dumps({'type':'complete','count':len(buildings_found)})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stream_scan(state, min_sqft, max_res):
    from scanner import (
        build_overpass_query,
        query_overpass,
        polygon_area_sqft,
        polygon_centroid,
        reverse_geocode,
        format_building_name,
    )
    import time

    bbox = STATE_BBOX[state]
    query = build_overpass_query(bbox)
    elements = query_overpass(query)

    count = 0
    for el in elements:
        geom = el.get("geometry", [])
        if not geom:
            continue

        area = polygon_area_sqft(geom)
        if area < min_sqft:
            continue

        lat, lon = polygon_centroid(geom)
        tags = el.get("tags", {})
        btype = tags.get("building", "commercial").replace("_", " ").title()

        time.sleep(1.0)  # Nominatim rate limit
        geo = reverse_geocode(lat, lon)
        name = format_building_name(tags, geo, btype)
        road = geo.get("road", "")
        city = geo.get("city", "")
        postcode = geo.get("postcode", "")
        address = f"{road}, {city}, {state} {postcode}".strip(", ") or geo.get("display_name", "")[:80]

        yield {
            "id": f"osm_{el['id']}",
            "osm_id": el["id"],
            "name": name,
            "address": address,
            "city": city or state,
            "state": state,
            "lat": round(lat, 6),
            "lng": round(lon, 6),
            "zoom": 17 if area < 500_000 else 16,
            "roof_sqft": int(area),
            "building_type": btype,
            "osm_tags": tags,
            "leed": tags.get("green_rating", "Unknown"),
            "sbti": False,
            "esg_score": 50,
            "net_zero_year": "N/A",
            "roof_polygon": [[g["lat"], g["lon"]] for g in geom[:20]],
            "cooling_towers": 0,
            "roof_conf": 0.0,
            "tower_conf": 0.0,
            "annual_water_bill": int(area * 0.0015),
        }

        count += 1
        if count >= max_res:
            break


def _cv_screen_and_score(b):
    """
    Candidate discovery comes from OSM/Overpass.
    Physical screening comes from CV on ESRI imagery.
    CV is run ONCE during scan and stored in _cv_cache for later detail views.
    """
    b2 = dict(b)

    cv_result = None

    if CV_AVAILABLE:
        try:
            cv_result = run_pipeline(b2)

            if "error" not in cv_result:
                b2["roof_sqft"] = int(cv_result["roof"].get("area_sqft", b2.get("roof_sqft", 0)))
                b2["cooling_towers"] = int(cv_result["towers"].get("count", 0))
                b2["roof_conf"] = float(cv_result["roof"].get("confidence", 0.0))
                b2["tower_conf"] = float(cv_result["towers"].get("confidence", 0.0))
                b2["cv"] = {
                        "source": cv_result.get("source"),
                         "cv_model": cv_result.get("cv_model"),
                         "roof": cv_result.get("roof"),
                         "towers": cv_result.get("towers"),
                         "annotated_b64": cv_result.get("annotated_b64"),
                         "saved_files": {
                             "annotated_path": (cv_result.get("saved_files") or {}).get("annotated_path")
                         },
                }
        except Exception as e:
            b2["cv_error"] = str(e)

    sc = calculate_viability(
        b2,
        roof_conf=b2.get("roof_conf", 0.0),
        tower_conf=b2.get("tower_conf", 0.5 if b2.get("cooling_towers", 0) == 0 else 0.0),
    )

    # Save scan-time CV for detail page so it is NOT rerun later
    if cv_result and "error" not in cv_result and b2.get("osm_id") is not None:
        _cache_cv_result(b2["osm_id"], b2, cv_result, sc)

    return {**b2, "score": sc}


# ── /api/cv/<osm_id> ──────────────────────────────────────────────────────

@app.route("/api/cv/<osm_id>", methods=["POST"])
def api_cv(osm_id):
    """
    Return cached scan-time CV only.
    Do NOT rerun live CV on building open.
    """
    cache_key = _normalize_osm_id(osm_id)

    if cache_key in _cv_cache:
        return jsonify(_cv_cache[cache_key])

    return jsonify({
        "error": f"Cached CV for OSM:{cache_key} not found. Run /api/scan first so CV is computed during scan.",
        "cached_only": True,
    }), 404


# ── /api/roi ──────────────────────────────────────────────────────────────

@app.route("/api/roi")
def api_roi():
    sqft = float(request.args.get("roof_sqft", 100_000))
    rain = float(request.args.get("rainfall_in", 34))
    wrate = float(request.args.get("water_rate", 4.20))
    srate = float(request.args.get("sewage_rate", 3.50))

    gal = harvest_gallons_per_year(sqft, rain)
    sav = annual_savings_usd(gal, wrate, srate)

    return jsonify({
        "harvest_gallons": round(gal),
        "annual_savings_usd": round(sav, 2),
        "capex_usd": round(sqft * 0.28, 2),
        "payback_years": payback_years(sqft, sav),
        "co2_offset_kg": round(gal * 0.579 / 1000, 2),
        "formula": "sqft × rainfall_in × 0.623 × 0.85  [FEMP/ARCSA]",
    })


# ── STARTUP ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  RainUSE Nexus — Real Building Discovery Engine")
    print("=" * 60)
    print("  Discovery:    Overpass API (OpenStreetMap) — real-time")
    print("  Geocoding:    Nominatim — free, no API key")
    print("  Satellite:    ESRI World Imagery (Maxar)")
    print(f"  CV available: {CV_AVAILABLE}")
    print("  States:       All 48 continental US states")
    print("  Candidate threshold: 60,000 sq ft")
    print("  Final CV threshold:  100,000 sq ft (challenge req)")
    print("  Scan endpoint: POST /api/scan")
    print('  Example body: {"state":"Texas","candidate_min_sqft":60000,"final_min_sqft":100000,"max_results":15}')
    print("=" * 60)
    print("\n  API: http://localhost:5000/api/")
    print("\n  Open frontend/index.html in browser.\n")
    app.run(debug=True, port=5000, threaded=True)
