"""
scanner.py — Real Building Discovery Engine
============================================
Queries the OpenStreetMap Overpass API (free, no API key) to discover
ALL commercial/industrial buildings in a given US state.

The app does NOT know which buildings exist beforehand.
It finds them by scanning satellite-verified building footprint data.

How it works:
1. Takes a US state name and minimum roof area threshold
2. Builds an Overpass QL query for that state's bounding box
3. Downloads all commercial/industrial building polygons
4. Calculates each building's roof area from GPS polygon coordinates
   using the Shoelace formula (geospatial area calculation)
5. Flags buildings with area > threshold (default: 100,000 sq ft)
6. Reverse-geocodes each address via Nominatim (free, no key)
7. Returns list of discovered buildings for CV pipeline processing

Data sources used:
- Building footprints: OpenStreetMap via Overpass API (overpass-api.de)
- Building tags: OSM commercial/industrial classification
- Addresses: Nominatim reverse geocoding (nominatim.openstreetmap.org)
- Area formula: Shoelace / Gauss's area formula on geographic coordinates
"""

import math
import time
import requests

# ── State Bounding Boxes ─────────────────────────────────────────────────
# Format: [south_lat, west_lng, north_lat, east_lng]
# Source: US Census Bureau state boundary data
STATE_BBOX = {
    "Alabama":        [30.14, -88.47, 35.01, -84.89],
    "Arizona":        [31.33, -114.82, 37.00, -109.05],
    "Arkansas":       [33.00, -94.62, 36.50, -89.64],
    "California":     [32.53, -124.41, 42.01, -114.13],
    "Colorado":       [36.99, -109.06, 41.00, -102.04],
    "Connecticut":    [40.99, -73.73, 42.05, -71.79],
    "Delaware":       [38.45, -75.79, 39.84, -75.05],
    "Florida":        [24.39, -87.63, 31.00, -80.03],
    "Georgia":        [30.36, -85.61, 35.00, -80.84],
    "Idaho":          [41.99, -117.24, 49.00, -111.04],
    "Illinois":       [36.97, -91.51, 42.51, -87.02],
    "Indiana":        [37.77, -88.10, 41.76, -84.78],
    "Iowa":           [40.38, -96.64, 43.50, -90.14],
    "Kansas":         [36.99, -102.05, 40.00, -94.59],
    "Kentucky":       [36.50, -89.57, 39.15, -81.96],
    "Louisiana":      [28.93, -94.04, 33.02, -88.82],
    "Maine":          [43.06, -71.08, 47.46, -66.95],
    "Maryland":       [37.91, -79.49, 39.72, -75.05],
    "Massachusetts":  [41.24, -73.51, 42.89, -69.93],
    "Michigan":       [41.70, -90.42, 48.19, -82.42],
    "Minnesota":      [43.50, -97.24, 49.38, -89.49],
    "Mississippi":    [30.17, -91.65, 35.01, -88.10],
    "Missouri":       [35.99, -95.77, 40.61, -89.10],
    "Montana":        [44.36, -116.05, 49.00, -104.04],
    "Nebraska":       [40.00, -104.05, 43.00, -95.31],
    "Nevada":         [35.00, -120.01, 42.00, -114.04],
    "New Hampshire":  [42.70, -72.56, 45.31, -70.60],
    "New Jersey":     [38.93, -75.56, 41.36, -73.90],
    "New Mexico":     [31.33, -109.05, 37.00, -103.00],
    "New York":       [40.50, -79.76, 45.01, -71.86],
    "North Carolina": [33.84, -84.32, 36.59, -75.46],
    "North Dakota":   [45.94, -104.05, 49.00, -96.55],
    "Ohio":           [38.40, -84.82, 42.33, -80.52],
    "Oklahoma":       [33.62, -103.00, 37.00, -94.43],
    "Oregon":         [41.99, -124.57, 46.24, -116.46],
    "Pennsylvania":   [39.72, -80.52, 42.27, -74.69],
    "Rhode Island":   [41.15, -71.91, 42.02, -71.12],
    "South Carolina": [32.05, -83.35, 35.21, -78.55],
    "South Dakota":   [42.48, -104.06, 45.95, -96.44],
    "Tennessee":      [34.98, -90.31, 36.68, -81.65],
    "Texas":          [25.84, -106.65, 36.50, -93.51],
    "Utah":           [36.99, -114.05, 42.00, -109.04],
    "Vermont":        [42.73, -73.44, 45.02, -71.46],
    "Virginia":       [36.54, -83.68, 39.46, -75.24],
    "Washington":     [45.54, -124.73, 49.00, -116.92],
    "West Virginia":  [37.20, -82.64, 40.64, -77.72],
    "Wisconsin":      [42.49, -92.89, 47.08, -86.25],
    "Wyoming":        [40.99, -111.06, 45.01, -104.05],
}

HEADERS = {
    "User-Agent": "RainUSE-Nexus/1.0 (Grundfos Water Prospecting; hackathon research)",
    "Accept": "application/json",
}


# ── Geographic Area Calculation ───────────────────────────────────────────
def polygon_area_sqft(geometry: list) -> float:
    """
    Calculate the area of a geographic polygon in square feet.

    Uses the Shoelace (Gauss's area) formula adapted for lat/lng coordinates,
    with a spherical Earth approximation (R = 6,371,000 m).

    Args:
        geometry: list of {"lat": float, "lon": float} dicts from Overpass

    Returns:
        Area in square feet (0 if polygon too small to calculate)
    """
    if not geometry or len(geometry) < 3:
        return 0.0

    R = 6_371_000  # Earth radius, meters
    lats = [math.radians(g["lat"]) for g in geometry]
    lons = [math.radians(g["lon"]) for g in geometry]

    area = 0.0
    n = len(lats)
    for i in range(n):
        j = (i + 1) % n
        area += (lons[j] - lons[i]) * (2 + math.sin(lats[i]) + math.sin(lats[j]))

    area_m2  = abs(area * R * R / 2.0)
    area_sqft = area_m2 * 10.7639  # 1 m² = 10.7639 ft²
    return area_sqft


def polygon_centroid(geometry: list) -> tuple:
    """Return (lat, lng) centroid of a polygon."""
    if not geometry:
        return 0.0, 0.0
    lat = sum(g["lat"] for g in geometry) / len(geometry)
    lon = sum(g["lon"] for g in geometry) / len(geometry)
    return lat, lon


# ── Overpass API Query ────────────────────────────────────────────────────
BUILDING_TYPES = (
    "commercial|industrial|warehouse|office|retail|manufacture|"
    "hospital|airport|"
    "data_center|factory"
)

def build_overpass_query(bbox: list, timeout: int = 60) -> str:
    """
    Build an Overpass QL query to find all commercial/industrial buildings
    within a bounding box.

    The query fetches building polygon geometries so we can calculate
    roof area from the coordinates using the Shoelace formula.

    bbox format: [south, west, north, east]
    """
    s, w, n, e = bbox
    bbox_str = f"{s},{w},{n},{e}"
    return f"""
[out:json][timeout:{timeout}];
(
  way["building"~"{BUILDING_TYPES}"]({bbox_str});
  way["building"="yes"]["landuse"~"industrial|commercial"]({bbox_str});
  way["landuse"~"industrial|commercial"]["building"]({bbox_str});
);
out body geom;
"""


def query_overpass(query: str, retries: int = 2) -> list:
    """
    Send query to Overpass API and return list of building elements.
    Tries multiple public endpoints and gives better error messages.
    """
    urls = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://z.overpass-api.de/api/interpreter",
    ]

    last_error = None

    for url in urls:
        for attempt in range(retries + 1):
            try:
                resp = requests.post(
                    url,
                    data={"data": query},
                    headers=HEADERS,
                    timeout=90,
                )

                resp.raise_for_status()
                return resp.json().get("elements", [])

            except requests.exceptions.Timeout as e:
                last_error = f"{url} timeout: {e}"
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue

            except requests.exceptions.HTTPError as e:
                last_error = f"{url} HTTP error: {e}"
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue

            except Exception as e:
                last_error = f"{url} failed: {e}"
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue

        time.sleep(1)

    raise RuntimeError(f"Overpass API error: {last_error}")


# ── Reverse Geocoding ─────────────────────────────────────────────────────
def reverse_geocode(lat: float, lon: float) -> dict:
    """
    Get a human-readable address for GPS coordinates using Nominatim.
    Free, no API key required. Rate limit: 1 request/second.

    Returns dict with: display_name, road, city, postcode, state
    """
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "json", "zoom": 18}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        addr = data.get("address", {})
        return {
            "display_name": data.get("display_name", f"{lat:.4f}N, {abs(lon):.4f}W"),
            "road":         addr.get("road", addr.get("street", "")),
            "city":         addr.get("city", addr.get("town", addr.get("village", ""))),
            "postcode":     addr.get("postcode", ""),
            "state":        addr.get("state", ""),
            "building_name": addr.get("building", ""),
        }
    except Exception:
        return {
            "display_name": f"{lat:.4f}°N {abs(lon):.4f}°W",
            "road": "", "city": "", "postcode": "", "state": "", "building_name": "",
        }


# ── Format Building Name ──────────────────────────────────────────────────
def format_building_name(tags: dict, geocode: dict, building_type: str) -> str:
    """
    Build a human-readable building name from OSM tags + geocode result.
    Priority: OSM name tag → geocoded building name → type + address
    """
    name = tags.get("name", "") or tags.get("operator", "") or geocode.get("building_name", "")
    if name:
        return name
    road  = geocode.get("road", "")
    city  = geocode.get("city", "")
    btype = building_type.replace("_", " ").title()
    if road:
        return f"{btype} — {road}{', ' + city if city else ''}"
    return f"{btype} Building"


# ── Main Scanner ──────────────────────────────────────────────────────────
def scan_state(
    state_name: str,
    min_sqft: int = 100_000,
    max_results: int = 20,
    progress_callback=None,
) -> list:
    """
    Discover all qualifying commercial buildings in a US state.

    This is the core engine. It discovers buildings it has never seen before.

    Args:
        state_name:        One of the 48 continental US states
        min_sqft:          Minimum roof area threshold (default: 100,000 sq ft)
        max_results:       Cap on returned results (for demo performance)
        progress_callback: Optional fn(message: str) for streaming progress

    Returns:
        List of discovered building dicts, sorted by roof_sqft descending
    """
    def log(msg):
        if progress_callback:
            progress_callback(msg)
        print(f"  [SCAN] {msg}")

    bbox = STATE_BBOX.get(state_name)
    if not bbox:
        raise ValueError(f"State '{state_name}' not in bounding box database")

    log(f"Querying Overpass API for {state_name}...")
    log(f"Bounding box: {bbox[0]}°N–{bbox[2]}°N, {bbox[1]}°W–{bbox[3]}°W")
    log(f"Filtering: building area > {min_sqft:,} sq ft (= {min_sqft/10.764:.0f} m²)")

    query    = build_overpass_query(bbox)
    elements = query_overpass(query)

    log(f"Raw OSM results: {len(elements)} building polygons")
    log("Calculating roof areas from polygon coordinates (Shoelace formula)...")

    discovered = []
    geocoded   = 0

    for el in elements:
        geom = el.get("geometry", [])
        if not geom:
            continue

        area_sqft = polygon_area_sqft(geom)
        if area_sqft < min_sqft:
            continue  # Below threshold — skip

        lat, lon  = polygon_centroid(geom)
        tags      = el.get("tags", {})
        btype     = (
            tags.get("building", "commercial")
            .replace("_", " ").replace("=", " ").title()
        )

        # Rate-limited geocoding (1 req/sec per Nominatim policy)
        time.sleep(1.0)
        geo  = reverse_geocode(lat, lon)
        name = format_building_name(tags, geo, btype)
        geocoded += 1

        road     = geo.get("road", "")
        city     = geo.get("city", "")
        postcode = geo.get("postcode", "")
        address  = f"{road}, {city}, {state_name} {postcode}".strip(", ")
        if not road:
            address = geo.get("display_name", f"{lat:.4f}°N {abs(lon):.4f}°W")[:80]

        building = {
            "id":           f"osm_{el['id']}",          # OSM way ID — guaranteed unique
            "osm_id":       el["id"],
            "name":         name,
            "address":      address,
            "city":         city or state_name,
            "state":        state_name,
            "lat":          round(lat, 6),
            "lng":          round(lon, 6),
            "zoom":         17 if area_sqft < 500_000 else 16,
            "roof_sqft":    int(area_sqft),
            "building_type": btype,
            "osm_tags":     tags,
            # OSM doesn't reliably have LEED/ESG — these come from financial scoring
            "leed":         tags.get("green_rating", tags.get("certification", "Unknown")),
            "sbti":         False,   # Would come from SEC EDGAR scrape
            "esg_score":    50,      # Default — updated by SEC EDGAR module
            "net_zero_year": "N/A",
            # Roof polygon for map overlay (first 20 points, enough for display)
            "roof_polygon": [[g["lat"], g["lon"]] for g in geom[:20]],
            "cooling_towers": 0,     # Will be set by CV pipeline
            "roof_conf":     0.0,    # Will be set by CV pipeline
            "tower_conf":    0.0,    # Will be set by CV pipeline
            "annual_water_bill": 0,  # Will be estimated from area + state rate
        }

        log(f"✓ FOUND: {name[:50]} | {int(area_sqft):,} sq ft | {address[:40]}")
        discovered.append(building)

        if len(discovered) >= max_results:
            log(f"Max results ({max_results}) reached — stopping scan")
            break

    log(f"Scan complete: {len(discovered)} buildings >{min_sqft:,} sq ft found in {state_name}")
    log(f"Reverse-geocoded: {geocoded} addresses")

    # Sort by roof area descending (largest = highest harvest potential)
    discovered.sort(key=lambda b: b["roof_sqft"], reverse=True)
    return discovered
