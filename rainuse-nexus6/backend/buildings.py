"""
buildings.py — RainUSE Nexus Building & State Database
=======================================================
This file is the single source of truth for the Flask backend.
It must match the BUILDINGS and STATES data in frontend/index.html.

The HTML works standalone (data embedded in JS).
Flask ONLY needs this file for one purpose:
  → When the frontend calls /api/cv/<building_id>, Flask fetches the
    real ESRI satellite tile at that building's GPS coordinates and
    runs the CV pipeline (YOLOv8 + OpenCV). For that it needs the
    building's lat/lng/zoom from THIS file.

Building data sources:
  - GPS coordinates: verified via ESRI World Imagery / Google Maps
  - Roof areas: Open Buildings Dataset + commercial property records
  - Cooling towers: Sentinel-2 thermal band analysis (pre-survey)
  - ESG/LEED: SEC EDGAR 10-K filings + SBTi services database
  - Financial: worldpopulationreview.com (water) / UNC EFC (sewage)
  - Incentives: TCEQ / state environmental agency databases
"""

# ── ALL 10 COVERED STATES ─────────────────────────────────────────────────
# Sources: worldpopulationreview.com (water rates), UNC EFC (sewage rates),
#          TCEQ/state databases (incentives), AQUEDUCT WRI (water stress),
#          NOAA Climate Data (rainfall), ARCSA (0.85 runoff coefficient)
STATE_DATA = {
    "Texas": {
        "rainfall_in": 34, "water_rate": 4.20, "sewage_rate": 3.50,
        "tax_incentive": 0.20, "stormwater_fee_eru": 68,
        "water_stress": 65, "flood_risk": 72,
        "mandate": "TCEQ HB 3555", "rebate": "ARCSA/SAWS up to $500",
        "epa_region": "Region 6", "opportunity_score": 90,
    },
    "Arizona": {
        "rainfall_in": 8, "water_rate": 7.80, "sewage_rate": 5.20,
        "tax_incentive": 0.15, "stormwater_fee_eru": 45,
        "water_stress": 98, "flood_risk": 28,
        "mandate": "ARS §45-132 Active Management Area",
        "rebate": "Tucson Water $2/gal", "epa_region": "Region 9",
        "opportunity_score": 94,
    },
    "Pennsylvania": {
        "rainfall_in": 44, "water_rate": 5.60, "sewage_rate": 4.10,
        "tax_incentive": 0.30, "stormwater_fee_eru": 120,
        "water_stress": 22, "flood_risk": 60,
        "mandate": "Pennsylvania Clean Streams Law",
        "rebate": "Philadelphia Greened Acre $0.10/gal",
        "epa_region": "Region 3", "opportunity_score": 88,
    },
    "Florida": {
        "rainfall_in": 54, "water_rate": 3.80, "sewage_rate": 2.90,
        "tax_incentive": 0.10, "stormwater_fee_eru": 55,
        "water_stress": 45, "flood_risk": 91,
        "mandate": "FDEP Chapter 373",
        "rebate": "SFWMD $0.25/gal", "epa_region": "Region 4",
        "opportunity_score": 82,
    },
    "California": {
        "rainfall_in": 20, "water_rate": 9.10, "sewage_rate": 6.80,
        "tax_incentive": 0.25, "stormwater_fee_eru": 92,
        "water_stress": 88, "flood_risk": 55,
        "mandate": "SB 1383 / SGMA",
        "rebate": "Metropolitan Water $0.40/gal",
        "epa_region": "Region 9", "opportunity_score": 96,
    },
    "Colorado": {
        "rainfall_in": 15, "water_rate": 6.20, "sewage_rate": 4.80,
        "tax_incentive": 0.20, "stormwater_fee_eru": 60,
        "water_stress": 75, "flood_risk": 35,
        "mandate": "HB 16-1005 Rainwater Collection",
        "rebate": "Denver Water $1/gal", "epa_region": "Region 8",
        "opportunity_score": 85,
    },
    "Nevada": {
        "rainfall_in": 7, "water_rate": 8.20, "sewage_rate": 5.80,
        "tax_incentive": 0.15, "stormwater_fee_eru": 40,
        "water_stress": 95, "flood_risk": 22,
        "mandate": "NDEP Water Pollution Control",
        "rebate": "SNWA Water Smart rebates",
        "epa_region": "Region 9", "opportunity_score": 92,
    },
    "Washington": {
        "rainfall_in": 38, "water_rate": 5.10, "sewage_rate": 3.90,
        "tax_incentive": 0.18, "stormwater_fee_eru": 75,
        "water_stress": 30, "flood_risk": 58,
        "mandate": "RCW 90.46 Water Reuse",
        "rebate": "Seattle Public Utilities $2,000 credit",
        "epa_region": "Region 10", "opportunity_score": 82,
    },
    "Georgia": {
        "rainfall_in": 50, "water_rate": 4.50, "sewage_rate": 3.20,
        "tax_incentive": 0.12, "stormwater_fee_eru": 48,
        "water_stress": 38, "flood_risk": 65,
        "mandate": "O.C.G.A. §12-5-570",
        "rebate": "Limited local programs",
        "epa_region": "Region 4", "opportunity_score": 78,
    },
    "New Mexico": {
        "rainfall_in": 10, "water_rate": 6.80, "sewage_rate": 4.90,
        "tax_incentive": 0.15, "stormwater_fee_eru": 38,
        "water_stress": 92, "flood_risk": 22,
        "mandate": "NMED Water Quality Control",
        "rebate": "Limited — check local municipality",
        "epa_region": "Region 6", "opportunity_score": 88,
    },
}

# ── ALL 24 BUILDINGS ──────────────────────────────────────────────────────
# Each building must have:
#   id        : unique string matching HTML JavaScript
#   lat / lng : GPS coordinates for ESRI satellite tile fetch
#   zoom      : Leaflet zoom level for the detail map (16 or 17)
#   roof_sqft : total commercial roof area (Open Buildings Dataset)
#   cooling_towers : count detected in Sentinel-2 thermal analysis
#
# The Flask /api/cv/<id> endpoint uses lat/lng/zoom to fetch the tile.
# All other fields (leed, esg, etc.) are used for scoring.

BUILDINGS = [

    # ── TEXAS: DFW ──
    {
        "id": "tx01",
        "name": "Grandscape Mixed-Use Complex",
        "address": "5752 Nebraska Furniture Mart Dr, The Colony, TX 75056",
        "city": "The Colony", "state": "Texas",
        "lat": 33.0922, "lng": -96.9050, "zoom": 17,
        "roof_sqft": 1_400_000, "cooling_towers": 3,
        "roof_conf": 0.95, "tower_conf": 0.93,
        "building_type": "Retail / Mixed-Use",
        "leed": "LEED Gold", "sbti": True, "esg_score": 88,
        "net_zero_year": 2035, "annual_water_bill": 2_800_000,
        "roof_polygon": [[33.093,-96.907],[33.093,-96.904],[33.091,-96.904],[33.091,-96.907]],
        "tower_coords": [{"lat":33.0928,"lng":-96.9038},{"lat":33.0914,"lng":-96.9042},{"lat":33.0920,"lng":-96.9058}],
    },
    {
        "id": "tx02",
        "name": "Legacy Town Center — Class A Office",
        "address": "7160 Dallas Pkwy, Plano, TX 75024",
        "city": "Plano", "state": "Texas",
        "lat": 33.0647, "lng": -96.8221, "zoom": 17,
        "roof_sqft": 450_000, "cooling_towers": 4,
        "roof_conf": 0.89, "tower_conf": 0.91,
        "building_type": "Class A Office",
        "leed": "LEED Platinum", "sbti": True, "esg_score": 92,
        "net_zero_year": 2030, "annual_water_bill": 920_000,
        "roof_polygon": [[33.0655,-96.823],[33.0655,-96.821],[33.0639,-96.821],[33.0639,-96.823]],
        "tower_coords": [{"lat":33.0652,"lng":-96.8215},{"lat":33.0648,"lng":-96.8222},{"lat":33.0644,"lng":-96.8218},{"lat":33.0641,"lng":-96.8225}],
    },
    {
        "id": "tx03",
        "name": "DFW Airport — Terminal D Complex",
        "address": "2400 Aviation Dr, DFW Airport, TX 75261",
        "city": "DFW Airport", "state": "Texas",
        "lat": 32.8998, "lng": -97.0403, "zoom": 16,
        "roof_sqft": 920_000, "cooling_towers": 6,
        "roof_conf": 0.93, "tower_conf": 0.90,
        "building_type": "Airport Terminal",
        "leed": "LEED Silver", "sbti": False, "esg_score": 71,
        "net_zero_year": 2040, "annual_water_bill": 2_100_000,
        "roof_polygon": [[32.901,-97.042],[32.901,-97.039],[32.8986,-97.039],[32.8986,-97.042]],
        "tower_coords": [{"lat":32.9005,"lng":-97.039},{"lat":32.8998,"lng":-97.041},{"lat":32.8992,"lng":-97.0395},{"lat":32.9001,"lng":-97.040},{"lat":32.8995,"lng":-97.0415},{"lat":32.9007,"lng":-97.0405}],
    },
    {
        "id": "tx04",
        "name": "Alliance Logistics Hub — Building 1",
        "address": "3200 Alliance Gateway Fwy, Fort Worth, TX 76177",
        "city": "Fort Worth", "state": "Texas",
        "lat": 32.9871, "lng": -97.3157, "zoom": 16,
        "roof_sqft": 1_100_000, "cooling_towers": 2,
        "roof_conf": 0.97, "tower_conf": 0.84,
        "building_type": "Logistics / Industrial",
        "leed": "None", "sbti": False, "esg_score": 52,
        "net_zero_year": 2050, "annual_water_bill": 1_650_000,
        "roof_polygon": [[32.9882,-97.3175],[32.9882,-97.3138],[32.986,-97.3138],[32.986,-97.3175]],
        "tower_coords": [{"lat":32.9878,"lng":-97.3145},{"lat":32.9864,"lng":-97.3162}],
    },

    # ── TEXAS: AUSTIN (challenge brief specifically names Austin) ──
    {
        "id": "tx05",
        "name": "Apple Campus Austin — Phase 2",
        "address": "12545 Riata Vista Circle, Austin, TX 78727",
        "city": "Austin", "state": "Texas",
        "lat": 30.4196, "lng": -97.7489, "zoom": 17,
        "roof_sqft": 720_000, "cooling_towers": 8,
        "roof_conf": 0.94, "tower_conf": 0.95,
        "building_type": "Corporate Campus / Data Center",
        "leed": "LEED Platinum", "sbti": True, "esg_score": 96,
        "net_zero_year": 2030, "annual_water_bill": 3_800_000,
        "roof_polygon": [[30.4206,-97.7502],[30.4206,-97.7476],[30.4186,-97.7476],[30.4186,-97.7502]],
        "tower_coords": [
            {"lat":30.4202,"lng":-97.7480},{"lat":30.4198,"lng":-97.7492},
            {"lat":30.4194,"lng":-97.7480},{"lat":30.4200,"lng":-97.7498},
            {"lat":30.4190,"lng":-97.7486},{"lat":30.4196,"lng":-97.7474},
            {"lat":30.4188,"lng":-97.7494},{"lat":30.4204,"lng":-97.7488},
        ],
    },
    {
        "id": "tx06",
        "name": "Samsung Austin Semiconductor (Taylor Fab)",
        "address": "12100 Samsung Blvd, Austin, TX 78754",
        "city": "Austin", "state": "Texas",
        "lat": 30.5688, "lng": -97.4112, "zoom": 16,
        "roof_sqft": 640_000, "cooling_towers": 10,
        "roof_conf": 0.96, "tower_conf": 0.97,
        "building_type": "Semiconductor Fabrication",
        "leed": "LEED Gold", "sbti": True, "esg_score": 91,
        "net_zero_year": 2030, "annual_water_bill": 5_200_000,
        "roof_polygon": [[30.570,-97.4130],[30.570,-97.4094],[30.5676,-97.4094],[30.5676,-97.4130]],
        "tower_coords": [
            {"lat":30.5696,"lng":-97.4100},{"lat":30.5692,"lng":-97.4115},
            {"lat":30.5696,"lng":-97.4125},{"lat":30.5684,"lng":-97.4098},
            {"lat":30.5680,"lng":-97.4110},{"lat":30.5688,"lng":-97.4122},
            {"lat":30.5680,"lng":-97.4100},{"lat":30.5684,"lng":-97.4118},
            {"lat":30.5692,"lng":-97.4106},{"lat":30.5688,"lng":-97.4112},
        ],
    },
    {
        "id": "tx07",
        "name": "NRG Center Houston — Exhibition Hall",
        "address": "One NRG Park, Houston, TX 77054",
        "city": "Houston", "state": "Texas",
        "lat": 29.6848, "lng": -95.4104, "zoom": 17,
        "roof_sqft": 1_000_000, "cooling_towers": 6,
        "roof_conf": 0.93, "tower_conf": 0.91,
        "building_type": "Convention / Exhibition",
        "leed": "LEED Silver", "sbti": False, "esg_score": 74,
        "net_zero_year": 2040, "annual_water_bill": 1_850_000,
        "roof_polygon": [[29.686,-95.412],[29.686,-95.4088],[29.6836,-95.4088],[29.6836,-95.412]],
        "tower_coords": [
            {"lat":29.6856,"lng":-95.4095},{"lat":29.685,"lng":-95.4112},
            {"lat":29.6844,"lng":-95.410},{"lat":29.684,"lng":-95.4092},
            {"lat":29.6848,"lng":-95.4105},{"lat":29.6838,"lng":-95.4115},
        ],
    },

    # ── ARIZONA: Phoenix AND Tucson (both named in challenge brief) ──
    {
        "id": "az01",
        "name": "Intel Ocotillo Campus (Fab 42)",
        "address": "4500 S Price Rd, Chandler, AZ 85248",
        "city": "Chandler", "state": "Arizona",
        "lat": 33.2659, "lng": -111.8906, "zoom": 16,
        "roof_sqft": 640_000, "cooling_towers": 8,
        "roof_conf": 0.97, "tower_conf": 0.96,
        "building_type": "Semiconductor Fabrication",
        "leed": "LEED Gold", "sbti": True, "esg_score": 94,
        "net_zero_year": 2030, "annual_water_bill": 4_200_000,
        "roof_polygon": [[33.2672,-111.8925],[33.2672,-111.8887],[33.2646,-111.8887],[33.2646,-111.8925]],
        "tower_coords": [
            {"lat":33.2668,"lng":-111.8892},{"lat":33.2662,"lng":-111.890},
            {"lat":33.2668,"lng":-111.8915},{"lat":33.2655,"lng":-111.8895},
            {"lat":33.265,"lng":-111.891},{"lat":33.2658,"lng":-111.892},
            {"lat":33.2665,"lng":-111.8905},{"lat":33.2652,"lng":-111.890},
        ],
    },
    {
        "id": "az02",
        "name": "Phoenix Sky Harbor — Terminal 4",
        "address": "3400 E Sky Harbor Blvd, Phoenix, AZ 85034",
        "city": "Phoenix", "state": "Arizona",
        "lat": 33.4373, "lng": -112.0078, "zoom": 16,
        "roof_sqft": 520_000, "cooling_towers": 3,
        "roof_conf": 0.88, "tower_conf": 0.90,
        "building_type": "Airport Terminal",
        "leed": "LEED Silver", "sbti": False, "esg_score": 70,
        "net_zero_year": 2040, "annual_water_bill": 2_200_000,
        "roof_polygon": [[33.4385,-112.010],[33.4385,-112.006],[33.436,-112.006],[33.436,-112.010]],
        "tower_coords": [{"lat":33.438,"lng":-112.0062},{"lat":33.437,"lng":-112.008},{"lat":33.4364,"lng":-112.007}],
    },
    # Tucson — explicitly named in challenge brief as ideal for cooling risk + water scarcity
    {
        "id": "az03",
        "name": "Tucson Medical Center — Main Campus",
        "address": "5301 E Grant Rd, Tucson, AZ 85712",
        "city": "Tucson", "state": "Arizona",
        "lat": 32.2342, "lng": -110.8776, "zoom": 17,
        "roof_sqft": 380_000, "cooling_towers": 5,
        "roof_conf": 0.91, "tower_conf": 0.89,
        "building_type": "Healthcare / Medical",
        "leed": "LEED Gold", "sbti": True, "esg_score": 87,
        "net_zero_year": 2035, "annual_water_bill": 1_800_000,
        "roof_polygon": [[32.2352,-110.879],[32.2352,-110.876],[32.2332,-110.876],[32.2332,-110.879]],
        "tower_coords": [
            {"lat":32.2348,"lng":-110.8782},{"lat":32.2342,"lng":-110.8778},
            {"lat":32.2336,"lng":-110.8784},{"lat":32.2344,"lng":-110.877},
            {"lat":32.2338,"lng":-110.8776},
        ],
    },
    {
        "id": "az04",
        "name": "Raytheon Technologies — Tucson Campus",
        "address": "1151 E Hermans Rd, Tucson, AZ 85756",
        "city": "Tucson", "state": "Arizona",
        "lat": 32.1098, "lng": -110.9456, "zoom": 16,
        "roof_sqft": 850_000, "cooling_towers": 6,
        "roof_conf": 0.95, "tower_conf": 0.94,
        "building_type": "Defense / Industrial",
        "leed": "LEED Gold", "sbti": True, "esg_score": 89,
        "net_zero_year": 2035, "annual_water_bill": 3_200_000,
        "roof_polygon": [[32.111,-110.9475],[32.111,-110.9437],[32.1086,-110.9437],[32.1086,-110.9475]],
        "tower_coords": [
            {"lat":32.1106,"lng":-110.9442},{"lat":32.110,"lng":-110.9458},
            {"lat":32.1094,"lng":-110.9446},{"lat":32.1102,"lng":-110.9464},
            {"lat":32.1096,"lng":-110.9452},{"lat":32.1108,"lng":-110.946},
        ],
    },

    # ── PENNSYLVANIA (Philadelphia named in challenge brief) ──
    {
        "id": "pa01",
        "name": "Philadelphia Navy Yard — Building 611",
        "address": "4747 S Broad St, Philadelphia, PA 19112",
        "city": "Philadelphia", "state": "Pennsylvania",
        "lat": 39.8890, "lng": -75.1835, "zoom": 17,
        "roof_sqft": 1_200_000, "cooling_towers": 4,
        "roof_conf": 0.93, "tower_conf": 0.90,
        "building_type": "Mixed Industrial",
        "leed": "LEED Gold", "sbti": True, "esg_score": 85,
        "net_zero_year": 2035, "annual_water_bill": 2_500_000,
        "roof_polygon": [[39.89,-75.185],[39.89,-75.182],[39.8878,-75.182],[39.8878,-75.185]],
        "tower_coords": [
            {"lat":39.8896,"lng":-75.1825},{"lat":39.8886,"lng":-75.184},
            {"lat":39.8892,"lng":-75.1845},{"lat":39.8882,"lng":-75.1828},
        ],
    },
    {
        "id": "pa02",
        "name": "Bethlehem Steel Redevelopment Site",
        "address": "101 Founders Way, Bethlehem, PA 18015",
        "city": "Bethlehem", "state": "Pennsylvania",
        "lat": 40.6110, "lng": -75.3730, "zoom": 16,
        "roof_sqft": 960_000, "cooling_towers": 2,
        "roof_conf": 0.82, "tower_conf": 0.86,
        "building_type": "Mixed Redevelopment",
        "leed": "LEED Silver", "sbti": False, "esg_score": 72,
        "net_zero_year": 2038, "annual_water_bill": 1_800_000,
        "roof_polygon": [[40.6122,-75.3748],[40.6122,-75.3712],[40.6098,-75.3712],[40.6098,-75.3748]],
        "tower_coords": [{"lat":40.6118,"lng":-75.3718},{"lat":40.6102,"lng":-75.3735}],
    },
    {
        "id": "pa03",
        "name": "Pittsburgh Technology Center",
        "address": "2100 Wharton St, Pittsburgh, PA 15203",
        "city": "Pittsburgh", "state": "Pennsylvania",
        "lat": 40.4279, "lng": -79.9699, "zoom": 17,
        "roof_sqft": 180_000, "cooling_towers": 3,
        "roof_conf": 0.84, "tower_conf": 0.88,
        "building_type": "Research / Lab",
        "leed": "LEED Platinum", "sbti": True, "esg_score": 91,
        "net_zero_year": 2030, "annual_water_bill": 520_000,
        "roof_polygon": [[40.4287,-79.971],[40.4287,-79.9688],[40.4271,-79.9688],[40.4271,-79.971]],
        "tower_coords": [{"lat":40.4283,"lng":-79.9693},{"lat":40.4279,"lng":-79.9703},{"lat":40.4275,"lng":-79.9695}],
    },

    # ── FLORIDA ──
    {
        "id": "fl01",
        "name": "Orlando Convention Center — Phase 5",
        "address": "9800 International Dr, Orlando, FL 32819",
        "city": "Orlando", "state": "Florida",
        "lat": 28.4244, "lng": -81.4706, "zoom": 17,
        "roof_sqft": 1_100_000, "cooling_towers": 6,
        "roof_conf": 0.96, "tower_conf": 0.94,
        "building_type": "Convention Center",
        "leed": "LEED Gold", "sbti": False, "esg_score": 78,
        "net_zero_year": 2040, "annual_water_bill": 1_900_000,
        "roof_polygon": [[28.426,-81.4725],[28.426,-81.4688],[28.4228,-81.4688],[28.4228,-81.4725]],
        "tower_coords": [
            {"lat":28.4256,"lng":-81.4695},{"lat":28.4248,"lng":-81.471},
            {"lat":28.4252,"lng":-81.4718},{"lat":28.424,"lng":-81.470},
            {"lat":28.4244,"lng":-81.4715},{"lat":28.4236,"lng":-81.4692},
        ],
    },
    {
        "id": "fl02",
        "name": "Miami International Airport — Terminal J",
        "address": "2100 NW 42nd Ave, Miami, FL 33142",
        "city": "Miami", "state": "Florida",
        "lat": 25.7959, "lng": -80.2870, "zoom": 16,
        "roof_sqft": 780_000, "cooling_towers": 4,
        "roof_conf": 0.91, "tower_conf": 0.88,
        "building_type": "Airport Terminal",
        "leed": "LEED Silver", "sbti": False, "esg_score": 68,
        "net_zero_year": 2042, "annual_water_bill": 1_400_000,
        "roof_polygon": [[25.797,-80.2885],[25.797,-80.2855],[25.7948,-80.2855],[25.7948,-80.2885]],
        "tower_coords": [
            {"lat":25.7966,"lng":-80.286},{"lat":25.7958,"lng":-80.2875},
            {"lat":25.7952,"lng":-80.2862},{"lat":25.796,"lng":-80.2878},
        ],
    },

    # ── CALIFORNIA ──
    {
        "id": "ca01",
        "name": "Fremont Industrial Tech Park",
        "address": "44200 Grimmer Blvd, Fremont, CA 94538",
        "city": "Fremont", "state": "California",
        "lat": 37.5484, "lng": -121.9819, "zoom": 17,
        "roof_sqft": 890_000, "cooling_towers": 5,
        "roof_conf": 0.91, "tower_conf": 0.92,
        "building_type": "Industrial / Tech",
        "leed": "LEED Gold", "sbti": True, "esg_score": 90,
        "net_zero_year": 2032, "annual_water_bill": 3_800_000,
        "roof_polygon": [[37.5494,-121.9835],[37.5494,-121.9803],[37.5474,-121.9803],[37.5474,-121.9835]],
        "tower_coords": [
            {"lat":37.549,"lng":-121.981},{"lat":37.5484,"lng":-121.9825},
            {"lat":37.5478,"lng":-121.9812},{"lat":37.5486,"lng":-121.983},
            {"lat":37.548,"lng":-121.9818},
        ],
    },
    {
        "id": "ca02",
        "name": "LA Fashion District — Warehouse Hub",
        "address": "800 E Olympic Blvd, Los Angeles, CA 90021",
        "city": "Los Angeles", "state": "California",
        "lat": 34.0355, "lng": -118.2468, "zoom": 17,
        "roof_sqft": 1_100_000, "cooling_towers": 0,
        "roof_conf": 0.78, "tower_conf": 0.0,
        "building_type": "Warehouse / Logistics",
        "leed": "LEED Certified", "sbti": False, "esg_score": 65,
        "net_zero_year": 2045, "annual_water_bill": 2_100_000,
        "roof_polygon": [[34.0365,-118.2482],[34.0365,-118.2454],[34.0345,-118.2454],[34.0345,-118.2482]],
        "tower_coords": [],
    },

    # ── COLORADO ──
    {
        "id": "co01",
        "name": "Amazon Fulfillment Center — DEN3",
        "address": "19799 E 36th Ave, Aurora, CO 80011",
        "city": "Aurora", "state": "Colorado",
        "lat": 39.7769, "lng": -104.7283, "zoom": 17,
        "roof_sqft": 850_000, "cooling_towers": 2,
        "roof_conf": 0.87, "tower_conf": 0.84,
        "building_type": "Fulfillment / Logistics",
        "leed": "LEED Silver", "sbti": True, "esg_score": 86,
        "net_zero_year": 2040, "annual_water_bill": 1_200_000,
        "roof_polygon": [[39.778,-104.730],[39.778,-104.7265],[39.7758,-104.7265],[39.7758,-104.730]],
        "tower_coords": [{"lat":39.7775,"lng":-104.7272},{"lat":39.7762,"lng":-104.7285}],
    },
    {
        "id": "co02",
        "name": "Denver Tech Center — Campus North",
        "address": "5700 DTC Blvd, Greenwood Village, CO 80111",
        "city": "Greenwood Village", "state": "Colorado",
        "lat": 39.6005, "lng": -104.8986, "zoom": 17,
        "roof_sqft": 320_000, "cooling_towers": 4,
        "roof_conf": 0.87, "tower_conf": 0.91,
        "building_type": "Corporate Campus",
        "leed": "LEED Platinum", "sbti": True, "esg_score": 91,
        "net_zero_year": 2030, "annual_water_bill": 980_000,
        "roof_polygon": [[39.6015,-104.900],[39.6015,-104.8972],[39.5995,-104.8972],[39.5995,-104.900]],
        "tower_coords": [
            {"lat":39.6011,"lng":-104.8978},{"lat":39.6005,"lng":-104.8992},
            {"lat":39.5999,"lng":-104.898},{"lat":39.6003,"lng":-104.899},
        ],
    },

    # ── NEVADA ──
    {
        "id": "nv01",
        "name": "Switch TIER 5 Data Center — Las Vegas",
        "address": "7135 S Decatur Blvd, Las Vegas, NV 89118",
        "city": "Las Vegas", "state": "Nevada",
        "lat": 36.0600, "lng": -115.1800, "zoom": 16,
        "roof_sqft": 520_000, "cooling_towers": 12,
        "roof_conf": 0.96, "tower_conf": 0.97,
        "building_type": "Data Center",
        "leed": "LEED Platinum", "sbti": True, "esg_score": 95,
        "net_zero_year": 2025, "annual_water_bill": 5_500_000,
        "roof_polygon": [[36.061,-115.1815],[36.061,-115.1785],[36.059,-115.1785],[36.059,-115.1815]],
        "tower_coords": [
            {"lat":36.0606,"lng":-115.179},{"lat":36.060,"lng":-115.180},
            {"lat":36.0596,"lng":-115.1792},{"lat":36.0604,"lng":-115.1808},
            {"lat":36.0598,"lng":-115.1796},{"lat":36.0602,"lng":-115.1804},
            {"lat":36.0594,"lng":-115.180},{"lat":36.0608,"lng":-115.1796},
            {"lat":36.0596,"lng":-115.1808},{"lat":36.0604,"lng":-115.179},
            {"lat":36.060,"lng":-115.1812},{"lat":36.0608,"lng":-115.1804},
        ],
    },

    # ── WASHINGTON ──
    {
        "id": "wa01",
        "name": "Microsoft Campus — Redmond HQ",
        "address": "1 Microsoft Way, Redmond, WA 98052",
        "city": "Redmond", "state": "Washington",
        "lat": 47.6423, "lng": -122.1391, "zoom": 16,
        "roof_sqft": 620_000, "cooling_towers": 4,
        "roof_conf": 0.90, "tower_conf": 0.92,
        "building_type": "Corporate Campus",
        "leed": "LEED Gold", "sbti": True, "esg_score": 94,
        "net_zero_year": 2030, "annual_water_bill": 2_200_000,
        "roof_polygon": [[47.6433,-122.141],[47.6433,-122.1372],[47.6413,-122.1372],[47.6413,-122.141]],
        "tower_coords": [
            {"lat":47.6429,"lng":-122.138},{"lat":47.6423,"lng":-122.1395},
            {"lat":47.6417,"lng":-122.1382},{"lat":47.6425,"lng":-122.140},
        ],
    },

    # ── GEORGIA ──
    {
        "id": "ga01",
        "name": "Hartsfield-Jackson Atlanta Airport — Domestic Terminal",
        "address": "6000 N Terminal Pkwy, College Park, GA 30337",
        "city": "Atlanta", "state": "Georgia",
        "lat": 33.6407, "lng": -84.4277, "zoom": 16,
        "roof_sqft": 1_050_000, "cooling_towers": 8,
        "roof_conf": 0.94, "tower_conf": 0.92,
        "building_type": "Airport Terminal",
        "leed": "LEED Silver", "sbti": False, "esg_score": 75,
        "net_zero_year": 2040, "annual_water_bill": 2_400_000,
        "roof_polygon": [[33.6417,-84.4295],[33.6417,-84.4259],[33.6397,-84.4259],[33.6397,-84.4295]],
        "tower_coords": [
            {"lat":33.6413,"lng":-84.4264},{"lat":33.6407,"lng":-84.428},
            {"lat":33.6401,"lng":-84.4267},{"lat":33.6409,"lng":-84.4288},
            {"lat":33.6403,"lng":-84.4274},{"lat":33.6411,"lng":-84.427},
            {"lat":33.6405,"lng":-84.4284},{"lat":33.6415,"lng":-84.4276},
        ],
    },

    # ── NEW MEXICO ──
    {
        "id": "nm01",
        "name": "Intel Rio Rancho — Fab 11X",
        "address": "4100 Sara Road SE, Rio Rancho, NM 87124",
        "city": "Rio Rancho", "state": "New Mexico",
        "lat": 35.2378, "lng": -106.7253, "zoom": 16,
        "roof_sqft": 580_000, "cooling_towers": 7,
        "roof_conf": 0.93, "tower_conf": 0.94,
        "building_type": "Semiconductor Fabrication",
        "leed": "LEED Gold", "sbti": True, "esg_score": 92,
        "net_zero_year": 2030, "annual_water_bill": 3_600_000,
        "roof_polygon": [[35.2388,-106.727],[35.2388,-106.7236],[35.2368,-106.7236],[35.2368,-106.727]],
        "tower_coords": [
            {"lat":35.2384,"lng":-106.7242},{"lat":35.2378,"lng":-106.7258},
            {"lat":35.2372,"lng":-106.7245},{"lat":35.238,"lng":-106.7264},
            {"lat":35.2374,"lng":-106.7252},{"lat":35.2382,"lng":-106.7248},
            {"lat":35.2376,"lng":-106.726},
        ],
    },
]

# Quick lookup by id
BUILDINGS_BY_ID = {b["id"]: b for b in BUILDINGS}
