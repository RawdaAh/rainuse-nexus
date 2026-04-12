"""
score_engine.py — Viability Scoring Engine
===========================================
Calculates the holistic Grundfos RainUSE Viability Score for any building
discovered by the scanner, regardless of whether it was hardcoded or found
dynamically via the Overpass API.

Score = Physical(35%) + Financial(25%) + Environmental(25%) + ESG(15%)

All data sources cited inline.
"""

import math

# ── State Financial & Environmental Data ─────────────────────────────────
# Sources:
#   Water rates:    worldpopulationreview.com/state-rankings/water-prices-by-state
#   Sewage rates:   UNC EFC dashboard (efc.sog.unc.edu)
#   Tax incentives: TCEQ (Texas), state environmental agency databases
#   Water stress:   AQUEDUCT Water Risk Atlas (WRI)
#   Rainfall:       NOAA Climate Data Online (30-year normals)
#   Flood risk:     FEMA National Flood Hazard Layer + AQUEDUCT

STATE_FINANCIAL = {
    "Alabama":       {"rain":56,"wRate":3.20,"sRate":2.80,"inc":0.10,"swFee":30,"stress":28,"flood":68,"opp":72,"mandate":"Alabama ADEM","rebate":"Limited"},
    "Arizona":       {"rain":8, "wRate":7.80,"sRate":5.20,"inc":0.15,"swFee":45,"stress":98,"flood":28,"opp":94,"mandate":"ARS §45-132","rebate":"Tucson Water $2/gal"},
    "Arkansas":      {"rain":50,"wRate":2.90,"sRate":2.40,"inc":0.08,"swFee":25,"stress":32,"flood":72,"opp":68,"mandate":"ADEQ Stormwater","rebate":"Minimal"},
    "California":    {"rain":20,"wRate":9.10,"sRate":6.80,"inc":0.25,"swFee":92,"stress":88,"flood":55,"opp":96,"mandate":"SB 1383 / SGMA","rebate":"Metropolitan Water $0.40/gal"},
    "Colorado":      {"rain":15,"wRate":6.20,"sRate":4.80,"inc":0.20,"swFee":60,"stress":75,"flood":35,"opp":85,"mandate":"HB 16-1005","rebate":"Denver Water $1/gal"},
    "Connecticut":   {"rain":47,"wRate":5.80,"sRate":4.20,"inc":0.15,"swFee":65,"stress":20,"flood":55,"opp":74,"mandate":"DEEP MS4","rebate":"DEEP grants"},
    "Delaware":      {"rain":46,"wRate":4.90,"sRate":3.60,"inc":0.12,"swFee":50,"stress":18,"flood":60,"opp":70,"mandate":"DNREC Stormwater","rebate":"Limited"},
    "Florida":       {"rain":54,"wRate":3.80,"sRate":2.90,"inc":0.10,"swFee":55,"stress":45,"flood":91,"opp":82,"mandate":"FDEP Chapter 373","rebate":"SFWMD $0.25/gal"},
    "Georgia":       {"rain":50,"wRate":4.50,"sRate":3.20,"inc":0.12,"swFee":48,"stress":38,"flood":65,"opp":78,"mandate":"O.C.G.A. §12-5-570","rebate":"Limited"},
    "Idaho":         {"rain":12,"wRate":4.10,"sRate":3.00,"inc":0.10,"swFee":30,"stress":72,"flood":25,"opp":72,"mandate":"IDWR","rebate":"Minimal"},
    "Illinois":      {"rain":38,"wRate":4.40,"sRate":3.30,"inc":0.15,"swFee":52,"stress":22,"flood":58,"opp":76,"mandate":"IEPA NPDES","rebate":"IEPA grants"},
    "Indiana":       {"rain":42,"wRate":3.80,"sRate":2.90,"inc":0.10,"swFee":38,"stress":20,"flood":62,"opp":71,"mandate":"IDEM Stormwater","rebate":"Minimal"},
    "Iowa":          {"rain":35,"wRate":3.50,"sRate":2.70,"inc":0.10,"swFee":32,"stress":18,"flood":65,"opp":68,"mandate":"IDNR NPDES","rebate":"Minimal"},
    "Kansas":        {"rain":28,"wRate":3.80,"sRate":2.90,"inc":0.12,"swFee":35,"stress":65,"flood":45,"opp":74,"mandate":"KDA Water Rights","rebate":"Limited"},
    "Kentucky":      {"rain":48,"wRate":3.60,"sRate":2.80,"inc":0.10,"swFee":35,"stress":25,"flood":72,"opp":70,"mandate":"KY DEP","rebate":"Minimal"},
    "Louisiana":     {"rain":62,"wRate":2.80,"sRate":2.20,"inc":0.08,"swFee":28,"stress":38,"flood":94,"opp":76,"mandate":"LDEQ Stormwater","rebate":"Limited"},
    "Maine":         {"rain":45,"wRate":5.20,"sRate":3.80,"inc":0.15,"swFee":45,"stress":12,"flood":48,"opp":68,"mandate":"MEDEP","rebate":"Limited"},
    "Maryland":      {"rain":43,"wRate":5.40,"sRate":4.00,"inc":0.20,"swFee":80,"stress":25,"flood":65,"opp":79,"mandate":"MDE Stormwater","rebate":"Baltimore $2k credit"},
    "Massachusetts": {"rain":47,"wRate":5.90,"sRate":4.40,"inc":0.20,"swFee":75,"stress":22,"flood":58,"opp":78,"mandate":"MassDEP MS4","rebate":"MassDEP grants"},
    "Michigan":      {"rain":32,"wRate":4.20,"sRate":3.20,"inc":0.12,"swFee":42,"stress":15,"flood":52,"opp":70,"mandate":"EGLE Stormwater","rebate":"Limited"},
    "Minnesota":     {"rain":28,"wRate":3.90,"sRate":3.00,"inc":0.12,"swFee":40,"stress":18,"flood":55,"opp":70,"mandate":"MPCA MS4","rebate":"Limited"},
    "Mississippi":   {"rain":56,"wRate":2.70,"sRate":2.10,"inc":0.08,"swFee":22,"stress":30,"flood":75,"opp":68,"mandate":"MDEQ Stormwater","rebate":"Minimal"},
    "Missouri":      {"rain":42,"wRate":3.60,"sRate":2.80,"inc":0.10,"swFee":35,"stress":28,"flood":70,"opp":70,"mandate":"MoDNR","rebate":"Minimal"},
    "Montana":       {"rain":15,"wRate":4.80,"sRate":3.50,"inc":0.12,"swFee":30,"stress":55,"flood":30,"opp":72,"mandate":"MT DEQ","rebate":"Limited"},
    "Nebraska":      {"rain":28,"wRate":3.80,"sRate":2.90,"inc":0.10,"swFee":32,"stress":58,"flood":48,"opp":70,"mandate":"NDEE Water","rebate":"Minimal"},
    "Nevada":        {"rain":7, "wRate":8.20,"sRate":5.80,"inc":0.15,"swFee":40,"stress":95,"flood":22,"opp":92,"mandate":"NDEP","rebate":"SNWA rebates"},
    "New Hampshire": {"rain":46,"wRate":5.10,"sRate":3.80,"inc":0.15,"swFee":50,"stress":18,"flood":48,"opp":72,"mandate":"NHDES","rebate":"Limited"},
    "New Jersey":    {"rain":45,"wRate":5.60,"sRate":4.20,"inc":0.20,"swFee":85,"stress":28,"flood":68,"opp":78,"mandate":"NJDEP MS4","rebate":"NJ stormwater credit"},
    "New Mexico":    {"rain":10,"wRate":6.80,"sRate":4.90,"inc":0.15,"swFee":38,"stress":92,"flood":22,"opp":88,"mandate":"NMED Water Rights","rebate":"Limited"},
    "New York":      {"rain":46,"wRate":5.20,"sRate":3.90,"inc":0.20,"swFee":78,"stress":22,"flood":62,"opp":78,"mandate":"NYSDEC MS4","rebate":"NYC DEP green infra"},
    "North Carolina":{"rain":47,"wRate":4.20,"sRate":3.20,"inc":0.12,"swFee":45,"stress":32,"flood":72,"opp":74,"mandate":"NCDEQ","rebate":"Limited"},
    "North Dakota":  {"rain":18,"wRate":3.50,"sRate":2.70,"inc":0.10,"swFee":25,"stress":48,"flood":45,"opp":66,"mandate":"NDDEQ","rebate":"Minimal"},
    "Ohio":          {"rain":39,"wRate":4.10,"sRate":3.20,"inc":0.12,"swFee":45,"stress":18,"flood":60,"opp":72,"mandate":"Ohio EPA MS4","rebate":"Limited"},
    "Oklahoma":      {"rain":36,"wRate":3.40,"sRate":2.60,"inc":0.10,"swFee":30,"stress":55,"flood":65,"opp":72,"mandate":"ODEQ Stormwater","rebate":"Limited"},
    "Oregon":        {"rain":27,"wRate":5.80,"sRate":4.30,"inc":0.18,"swFee":65,"stress":45,"flood":42,"opp":78,"mandate":"Oregon DEQ","rebate":"Portland green credits"},
    "Pennsylvania":  {"rain":44,"wRate":5.60,"sRate":4.10,"inc":0.30,"swFee":120,"stress":22,"flood":60,"opp":88,"mandate":"Clean Streams Law","rebate":"Philadelphia $0.10/gal"},
    "Rhode Island":  {"rain":47,"wRate":5.40,"sRate":4.00,"inc":0.15,"swFee":58,"stress":18,"flood":55,"opp":72,"mandate":"RIDEM MS4","rebate":"Limited"},
    "South Carolina":{"rain":48,"wRate":3.90,"sRate":2.90,"inc":0.10,"swFee":38,"stress":32,"flood":78,"opp":72,"mandate":"SCDHEC","rebate":"Limited"},
    "South Dakota":  {"rain":20,"wRate":3.60,"sRate":2.70,"inc":0.10,"swFee":25,"stress":42,"flood":40,"opp":66,"mandate":"DENR Water","rebate":"Minimal"},
    "Tennessee":     {"rain":52,"wRate":3.50,"sRate":2.70,"inc":0.10,"swFee":38,"stress":25,"flood":70,"opp":72,"mandate":"TDEC","rebate":"Limited"},
    "Texas":         {"rain":34,"wRate":4.20,"sRate":3.50,"inc":0.20,"swFee":68,"stress":65,"flood":72,"opp":90,"mandate":"TCEQ HB 3555","rebate":"ARCSA/SAWS up to $500"},
    "Utah":          {"rain":12,"wRate":5.90,"sRate":4.20,"inc":0.15,"swFee":42,"stress":88,"flood":20,"opp":86,"mandate":"Utah DWR","rebate":"Salt Lake City rebates"},
    "Vermont":       {"rain":42,"wRate":5.00,"sRate":3.70,"inc":0.15,"swFee":52,"stress":12,"flood":48,"opp":70,"mandate":"VT DEC","rebate":"Limited"},
    "Virginia":      {"rain":43,"wRate":4.80,"sRate":3.60,"inc":0.15,"swFee":58,"stress":28,"flood":62,"opp":76,"mandate":"DEQ MS4","rebate":"VA SWM credits"},
    "Washington":    {"rain":38,"wRate":5.10,"sRate":3.90,"inc":0.18,"swFee":75,"stress":30,"flood":58,"opp":82,"mandate":"RCW 90.46","rebate":"Seattle Public Utilities $2k"},
    "West Virginia": {"rain":44,"wRate":3.20,"sRate":2.50,"inc":0.08,"swFee":28,"stress":18,"flood":68,"opp":64,"mandate":"DEP Stormwater","rebate":"Minimal"},
    "Wisconsin":     {"rain":32,"wRate":3.90,"sRate":3.00,"inc":0.12,"swFee":40,"stress":15,"flood":55,"opp":68,"mandate":"DNR MS4","rebate":"Limited"},
    "Wyoming":       {"rain":12,"wRate":4.50,"sRate":3.30,"inc":0.12,"swFee":28,"stress":62,"flood":18,"opp":72,"mandate":"DEQ Water","rebate":"Limited"},
}


# ── Core Formulas ─────────────────────────────────────────────────────────
def harvest_gallons_per_year(roof_sqft: float, rainfall_in: float) -> float:
    """
    FEMP Standard Rainwater Harvest Formula.
    Source: energy.gov/cmei/femp/articles/rainwater-harvesting-calculator
    ARCSA runoff coefficient 0.85 for commercial flat/low-slope roofs.
    """
    return roof_sqft * rainfall_in * 0.623 * 0.85


def annual_savings_usd(gallons: float, water_rate: float, sewage_rate: float) -> float:
    """
    Annual cost avoidance = water purchase savings + sewage discharge savings.
    Rates are $/1,000 gallons from worldpopulationreview.com and UNC EFC.
    """
    return gallons * (water_rate + sewage_rate) / 1000


def payback_years(roof_sqft: float, annual_savings: float) -> str:
    """
    Grundfos RainUSE compact system CAPEX estimated at $0.28/sq ft.
    Lower than industry average due to modular design (challenge brief).
    """
    if annual_savings <= 0:
        return "N/A"
    capex = roof_sqft * 0.28
    return f"{capex / annual_savings:.1f}"


def co2_offset_tons(gallons: float) -> float:
    """
    CO2 offset from avoided municipal water treatment + pumping.
    Source: US EPA — treating and pumping 1M gallons uses ~1,500 kWh.
    US average grid: 0.386 kg CO2/kWh (EPA eGrid 2023).
    Total: 1,500 × 0.386 = 579 kg CO2 per million gallons.
    """
    return round(gallons * 579 / 1_000_000, 2)


# ── Main Scoring Function ─────────────────────────────────────────────────
def calculate_viability(
    building: dict,
    roof_conf: float = None,
    tower_conf: float = None,
) -> dict:
    """
    Calculate holistic Viability Score for a discovered building.

    Works with ANY building dict — whether from Overpass discovery,
    manual entry, or CV pipeline output. Uses state name to look up
    financial data.

    Score axes:
      Physical (35%):     roof size + cooling towers + CV confidence
      Financial (25%):    water savings + incentives + stormwater fees
      Environmental (25%): rainfall + water stress + flood resilience
      ESG/Corporate (15%): LEED + SBTi + ESG score + net zero target

    Args:
        building:    Building dict (must have state, roof_sqft)
        roof_conf:   CV roof detection confidence (0–1), optional
        tower_conf:  CV tower detection confidence (0–1), optional
    """
    state_name = building.get("state", "Texas")
    s = STATE_FINANCIAL.get(state_name, STATE_FINANCIAL["Texas"])

    roof_sqft = building.get("roof_sqft", building.get("roof", 100_000))
    towers    = building.get("cooling_towers", building.get("towers", 0))
    leed      = building.get("leed", "None") or "None"
    sbti      = building.get("sbti", False)
    esg       = building.get("esg_score", building.get("esg", 50))

    # Use CV confidence from pipeline if provided, else use stored values
    rc = roof_conf if roof_conf is not None else building.get("roof_conf", 0.85)
    tc = tower_conf if tower_conf is not None else building.get("tower_conf", 0.80)

    # ── Physical (35%) ────────────────────────────────────────────────────
    roof_pts  = min(70, (roof_sqft / 1_200_000) * 65)
    tower_pts = min(30, towers * 3.5)
    conf_pts  = ((rc + (tc if towers > 0 else 0.5)) / 2) * 10
    physical  = min(100, roof_pts + tower_pts + conf_pts)

    # ── Financial (25%) ───────────────────────────────────────────────────
    gal  = harvest_gallons_per_year(roof_sqft, s["rain"])
    sav  = annual_savings_usd(gal, s["wRate"], s["sRate"])
    bill = building.get("annual_water_bill", max(sav * 3, 100_000))
    sav_ratio = min(80, (sav / max(bill, 1)) * 100 * 4)
    financial = min(100, sav_ratio + s["inc"] * 50 + min(10, s["swFee"] / 12))

    # ── Environmental (25%) ───────────────────────────────────────────────
    rain_pts  = min(40, (s["rain"] / 60) * 40)
    stress_pts = s["stress"] * 0.45
    flood_pts  = min(15, s["flood"] * 0.15)
    env = min(100, rain_pts + stress_pts + flood_pts)

    # ── ESG / Corporate (15%) ─────────────────────────────────────────────
    leed_map = {
        "LEED Platinum": 30, "LEED Gold": 22, "LEED Silver": 14,
        "LEED Certified": 8, "LEED": 8, "Unknown": 0, "None": 0,
    }
    leed_pts  = leed_map.get(leed, 0)
    sbti_pts  = 30 if sbti else 0
    esg_pts   = float(esg) * 0.40
    esg_score = min(100, leed_pts + sbti_pts + esg_pts)

    total = physical * 0.35 + financial * 0.25 + env * 0.25 + esg_score * 0.15

    return {
        "viability_score":   round(total, 1),
        "axes": {
            "physical":      round(physical, 1),
            "financial":     round(financial, 1),
            "environmental": round(env, 1),
            "esg":           round(esg_score, 1),
        },
        "roi": {
            "harvest_gallons_per_year": round(gal),
            "annual_savings_usd":       round(sav, 2),
            "capex_estimate_usd":       round(roof_sqft * 0.28),
            "payback_years":            payback_years(roof_sqft, sav),
            "co2_offset_tons_per_year": co2_offset_tons(gal),
            "trees_equivalent":         round(co2_offset_tons(gal) * 1000 / 21),
        },
        "state_data": {
            "rainfall_in":         s["rain"],
            "water_rate_per_kgal": s["wRate"],
            "sewage_rate_per_kgal":s["sRate"],
            "tax_incentive_pct":   s["inc"],
            "water_stress_index":  s["stress"],
            "flood_risk":          s["flood"],
            "opportunity_score":   s["opp"],
            "state_mandate":       s["mandate"],
            "rebate_program":      s["rebate"],
            "stormwater_fee_eru":  s["swFee"],
        },
    }
