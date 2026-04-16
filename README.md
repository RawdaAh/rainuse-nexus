# rainuse-nexus

# RainUSE Nexus / AquaVista  
**Grundfos · Automated Water Prospecting Engine**

RainUSE Nexus is a web-based prospecting tool for identifying high-potential commercial and industrial buildings for rainwater harvesting opportunities. The platform combines **building discovery**, **satellite imagery**, **computer vision**, and **financial/environmental scoring** to evaluate sites across U.S. states.

The system was developed as a prototype to support rapid, data-driven screening of large-roof facilities using real-time geographic and image-based analysis.

---

## Overview

The application works in two major stages:

1. **Candidate Discovery**
   - Queries **OpenStreetMap / Overpass API** to identify commercial and industrial buildings within a selected state
   - Filters buildings by approximate footprint area threshold

2. **Satellite-Based CV Screening**
   - Uses **ESRI World Imagery** satellite tiles
   - Estimates roof area using building-footprint-guided image analysis
   - Detects possible cooling towers using computer vision
   - Computes confidence scores and viability metrics

The output is a ranked list of candidate buildings with business-case and environmental indicators.

---

## Main Features

- Interactive U.S. state selection map
- Real-time building discovery using **Overpass API**
- Roof area estimation from **satellite imagery**
- Cooling tower screening using **computer vision**
- Building-level scoring based on:
  - physical suitability
  - financial value
  - environmental opportunity
  - ESG-related indicators
- Detailed building report view
- Rainwater harvesting calculator
- Exportable results workflow
- Frontend and backend deployed separately on Render

---

## Tech Stack

### Frontend
- HTML
- CSS
- JavaScript
- D3.js
- TopoJSON
- Leaflet

### Backend
- Python
- Flask
- Flask-CORS
- Requests
- Pillow
- NumPy
- OpenCV
- Ultralytics YOLO
- Shapely / PyProj

### External Data / APIs
- **Overpass API** — building discovery from OpenStreetMap
- **Nominatim** — reverse geocoding
- **ESRI World Imagery** — satellite imagery
- **worldpopulationreview.com** — water-rate reference
- **UNC EFC** — sewage-rate reference
- **FEMP / ARCSA** — rainwater harvesting formula basis

---

## Project Structure

```text
rainuse-nexus6/
│
├── backend/
│   ├── app.py
│   ├── cv_detector.py
│   ├── scanner.py
│   ├── score_engine.py
│   └── ...
│
├── frontend/
│   ├── index.html
│   └── ...
│
├── requirements.txt
├── run.py
└── README.md
