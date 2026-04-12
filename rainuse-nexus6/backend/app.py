"""
app.py — RainUSE Nexus Flask Backend
======================================
Run: python app.py

Core pipeline:
1. /api/scan discovers candidate commercial/industrial buildings in a state
   using Overpass / OpenStreetMap building footprints.
2. Each candidate is then CV-screened on ESRI World Imagery:
   - roof area estimated from image segmentation
   - cooling towers detected from imagery
   - confidence scores computed
3. Buildings are filtered by CV-estimated roof area threshold
   (default final_min_sqft = 100,000 sq ft).
4. Financial, environmental, and ESG scoring is applied.
5. Ranked results are returned.

Detailed per-building CV can also be re-run through:
  /api/cv/<osm_id>
"""

import sys, os, json, threading
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request, Response, stream_with_context
from flask_cors import CORS

from scanner     import scan_state, STATE_BBOX
from score_engine import calculate_viability, harvest_gallons_per_year, annual_savings_usd, payback_years

try:
    from cv_detector import run_pipeline
    CV_AVAILABLE = True
except Exception as e:
    CV_AVAILABLE = False
    print(f"  WARNING: CV detector not available: {e}")

app = Flask(__name__)
CORS(app)

_scan_cache = {}   # state → list of buildings (cache last scan)
_cv_cache   = {}   # osm_id → cv result


# ── /api/health ───────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({
        "status":            "ok",
        "cv_available":      CV_AVAILABLE,
        "states_available":  list(STATE_BBOX.keys()),
        "discovery_method":  "Overpass API (OpenStreetMap) — real-time discovery",
        "cv_model":          "YOLOv8n (Ultralytics) + OpenCV HSV Contour",
        "satellite_source":  "ESRI World Imagery (Maxar / Earthstar Geographics)",
        "harvest_formula":   "sqft × rainfall_in × 0.623 × 0.85  [FEMP / ARCSA]",
        "address_source":    "Nominatim (OpenStreetMap) reverse geocoding",
        "financial_source":  "worldpopulationreview.com | UNC EFC | TCEQ",
    })


# ── /api/states ───────────────────────────────────────────────────────────
@app.route("/api/states")
def api_states():
    """Returns all state financial + environmental data."""
    from score_engine import STATE_FINANCIAL
    return jsonify(STATE_FINANCIAL)


# ── /api/scan  ← THE MAIN ENDPOINT ───────────────────────────────────────
@app.route("/api/scan", methods=["POST"])
def api_scan():
    """
    Discovers ALL qualifying commercial buildings in a US state.

    POST body: {
        "state":     "Texas",
        "min_sqft":  100000,    # default: 100,000 sq ft (challenge requirement)
        "max_results": 50       # cap for demo performance
    }

    Process:
    1. Query Overpass API for all commercial/industrial building polygons
    2. Calculate each polygon's area using Shoelace formula
    3. Filter to area > min_sqft
    4. Reverse-geocode each address via Nominatim
    5. Score each building (financial + environmental + ESG)
    6. Return ranked results

    The app has NO prior knowledge of these buildings.
    """
    body = request.get_json(force=True) or {}
    state = body.get("state")
    if not state:
        return jsonify({"error": "Missing required field: state"}), 400
    candidate_min_sqft = int(body.get("candidate_min_sqft", 60_000))
    final_min_sqft = int(body.get("final_min_sqft", 100_000))
    max_res = int(body.get("max_results", 20))

    if state not in STATE_BBOX:
        return jsonify({"error": f"State '{state}' not supported"}), 400

    # Return cached scan if available (for re-renders)
    cache_key = f"{state}_{candidate_min_sqft}_{final_min_sqft}_{max_res}"
    if cache_key in _scan_cache:
        buildings = _scan_cache[cache_key]

        screened = [_cv_screen_and_score(b) for b in buildings]
        screened = [b for b in screened if b.get("roof_sqft", 0) >= final_min_sqft]
        screened.sort(key=lambda x: x["score"]["viability_score"], reverse=True)

        return jsonify({
            "state": state,
            "candidate_min_sqft": candidate_min_sqft,
            "final_min_sqft": final_min_sqft,
            "count": len(screened),
            "buildings": screened,
            "cached": True,
        })

    try:
        buildings = scan_state(state, min_sqft=candidate_min_sqft, max_results=max_res)
        _scan_cache[cache_key] = buildings
        screened = [_cv_screen_and_score(b) for b in buildings]
        screened = [b for b in screened if b.get("roof_sqft", 0) >= final_min_sqft]
        screened.sort(key=lambda x: x["score"]["viability_score"], reverse=True)
        return jsonify({
            "state": state,
            "candidate_min_sqft": candidate_min_sqft,
            "final_min_sqft": final_min_sqft,
            "count": len(screened),
            "buildings": screened,
            "cached": False,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /api/scan/stream  ← Server-Sent Events for real-time progress ─────────
@app.route("/api/scan/stream")
def api_scan_stream():
    """
    Stream candidate discovery + CV screening as Server-Sent Events.

    Query params:
      state
      candidate_min_sqft
      final_min_sqft
      max_results
    """
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
    """Generator that yields buildings one by one as they're discovered."""
    from scanner import build_overpass_query, query_overpass, polygon_area_sqft, polygon_centroid, reverse_geocode, format_building_name
    import time

    bbox     = STATE_BBOX[state]
    query    = build_overpass_query(bbox)
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
        tags     = el.get("tags", {})
        btype    = tags.get("building", "commercial").replace("_", " ").title()

        time.sleep(1.0)  # Nominatim rate limit
        geo     = reverse_geocode(lat, lon)
        name    = format_building_name(tags, geo, btype)
        road    = geo.get("road", "")
        city    = geo.get("city", "")
        postcode= geo.get("postcode", "")
        address = f"{road}, {city}, {state} {postcode}".strip(", ") or geo.get("display_name","")[:80]

        yield {
            "id":           f"osm_{el['id']}",
            "osm_id":       el["id"],
            "name":         name,
            "address":      address,
            "city":         city or state,
            "state":        state,
            "lat":          round(lat, 6),
            "lng":          round(lon, 6),
            "zoom":         17 if area < 500_000 else 16,
            "roof_sqft":    int(area),
            "building_type": btype,
            "osm_tags":     tags,
            "leed":         tags.get("green_rating", "Unknown"),
            "sbti":         False,
            "esg_score":    50,
            "net_zero_year": "N/A",
            "roof_polygon": [[g["lat"], g["lon"]] for g in geom[:20]],
            "cooling_towers": 0,
            "roof_conf":     0.0,
            "tower_conf":    0.0,
            "annual_water_bill": int(area * 0.0015),  # Estimate $1.50/sqft/yr
        }

        count += 1
        if count >= max_res:
            break


def _cv_screen_and_score(b):
    """
    Candidate discovery comes from OSM/Overpass.
    Physical target screening comes from CV on ESRI imagery.
    """
    b2 = dict(b)

    if CV_AVAILABLE:
        try:
            cv = run_pipeline(b2)

            if "error" not in cv:
                b2["roof_sqft"] = int(cv["roof"].get("area_sqft", b2.get("roof_sqft", 0)))
                b2["cooling_towers"] = int(cv["towers"].get("count", 0))
                b2["roof_conf"] = float(cv["roof"].get("confidence", 0.0))
                b2["tower_conf"] = float(cv["towers"].get("confidence", 0.0))
                b2["cv"] = {
                    "source": cv.get("source"),
                    "cv_model": cv.get("cv_model"),
                    "roof": cv.get("roof"),
                    "towers": cv.get("towers"),
                }
        except Exception as e:
            b2["cv_error"] = str(e)

    sc = calculate_viability(
        b2,
        roof_conf=b2.get("roof_conf", 0.0),
        tower_conf=b2.get("tower_conf", 0.5 if b2.get("cooling_towers", 0) == 0 else 0.0),
    )

    return {**b2, "score": sc}

# ── /api/cv/<osm_id>  ← Real CV pipeline ─────────────────────────────────
@app.route("/api/cv/<osm_id>", methods=["POST"])
def api_cv(osm_id):
    """
    Run the full CV pipeline on a discovered building.

    1. Look up building by OSM ID (from scan results)
    2. Fetch ESRI World Imagery tile at its GPS coordinates
    3. Run hybrid roof CV (classical segmentation + geospatial prior) → roof area + confidence
    4. Run high-zoom classical CV screening → cooling tower presence + confidence
    5. Annotate image with bounding boxes
    6. Return base64 image + all detection metrics
    """
    osm_id = str(osm_id).replace("osm_", "")
    # Find building in cache
    building = None
    for cache_key, buildings in _scan_cache.items():
        for b in buildings:
            if str(b.get("osm_id")) == str(osm_id) or b.get("id") == f"osm_{osm_id}":
                building = b
                break
        if building:
            break

    # Also accept POST body with building data directly
    if not building:
        body = request.get_json(silent=True) or {}
        if body.get("lat") and body.get("lng"):
            building = body

    if not building:
        return jsonify({"error": f"Building OSM:{osm_id} not found in scan cache. Run /api/scan first."}), 404

    cache_key = str(osm_id)
    if cache_key in _cv_cache:
        return jsonify(_cv_cache[cache_key])

    if not CV_AVAILABLE:
        return jsonify({"error": "CV not available", "fix": "pip install opencv-python-headless ultralytics"}), 503

    result = run_pipeline(building)
    if "error" not in result:
        result["viability_score"] = calculate_viability(
            building,
            roof_conf=result["roof"]["confidence"],
            tower_conf=result["towers"]["confidence"] if result["towers"]["count"] > 0 else 0.0,
        )
        _cv_cache[cache_key] = result

    return jsonify(result)


# ── /api/roi ──────────────────────────────────────────────────────────────
@app.route("/api/roi")
def api_roi():
    sqft   = float(request.args.get("roof_sqft",   100_000))
    rain   = float(request.args.get("rainfall_in",      34))
    wrate  = float(request.args.get("water_rate",      4.20))
    srate  = float(request.args.get("sewage_rate",     3.50))
    gal    = harvest_gallons_per_year(sqft, rain)
    sav    = annual_savings_usd(gal, wrate, srate)
    return jsonify({
        "harvest_gallons":    round(gal),
        "annual_savings_usd": round(sav, 2),
        "capex_usd":          round(sqft * 0.28, 2),
        "payback_years":      payback_years(sqft, sav),
        "co2_offset_kg":      round(gal * 0.579 / 1000, 2),
        "formula":            "sqft × rainfall_in × 0.623 × 0.85  [FEMP/ARCSA]",
    })


# ── STARTUP ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  RainUSE Nexus — Real Building Discovery Engine")
    print("="*60)
    print(f"  Discovery:    Overpass API (OpenStreetMap) — real-time")
    print(f"  Geocoding:    Nominatim — free, no API key")
    print(f"  Satellite:    ESRI World Imagery (Maxar)")
    print(f"  CV Model:     YOLOv8n + OpenCV — CV available: {CV_AVAILABLE}")
    print(f"  States:       All 48 continental US states")
    print(f"  Candidate threshold: 60,000 sq ft")
    print(f"  Final CV threshold:  100,000 sq ft (challenge req)")
    print(f"  Scan endpoint: POST /api/scan")
    print(f'  Example body: {{"state":"Texas","candidate_min_sqft":60000,"final_min_sqft":100000,"max_results":15}}')
    print("="*60)
    print(f"\n  API: http://localhost:5000/api/")
    print(f"\n  Open frontend/index.html in browser.\n")
    app.run(debug=True, port=5000, threaded=True)
