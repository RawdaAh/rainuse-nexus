"""
run.py  —  RainUSE Nexus startup script
Usage: python run.py

This script:
1. Checks Python version
2. Installs required packages
3. Tests the CV pipeline on one building
4. Starts the Flask backend server
5. Prints the URL to open in your browser
"""

import sys, os, subprocess

print("""
╔══════════════════════════════════════════════════════════╗
║     RainUSE Nexus — Grundfos Water Intelligence          ║
║     Automated Commercial Building Prospecting Engine     ║
╚══════════════════════════════════════════════════════════╝
""")

# ── Check Python version ──────────────────────────────────
if sys.version_info < (3, 9):
    print("ERROR: Python 3.9+ required. You have:", sys.version)
    sys.exit(1)
print(f"✓ Python {sys.version.split()[0]}")

# ── Install requirements ──────────────────────────────────
req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
print("Installing requirements (first run may take a minute)...")
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
    capture_output=True, text=True
)
if result.returncode != 0:
    print("WARNING: Some packages failed to install:", result.stderr[:300])
else:
    print("✓ All packages installed")

# ── Quick CV test ─────────────────────────────────────────
print("\nRunning quick CV pipeline test...")
backend_dir = os.path.join(os.path.dirname(__file__), "backend")
sys.path.insert(0, backend_dir)

try:
    from buildings import BUILDINGS
    from score_engine import calculate_viability
    test_bldg = BUILDINGS[0]
    score = calculate_viability(test_bldg)
    print(f"✓ Score engine OK — {test_bldg['name']}: {score['viability_score']:.1f}/100")
    print(f"  Harvest: {score['roi']['harvest_gallons_per_year']:,} gal/yr")
    print(f"  Savings: ${score['roi']['annual_savings_usd']:,.0f}/yr")
    print(f"  Payback: {score['roi']['payback_years']} years")
except Exception as e:
    print(f"WARNING: Score engine test failed: {e}")

# ── Print instructions ────────────────────────────────────
print("""
╔══════════════════════════════════════════════════════════╗
║                    READY TO LAUNCH                       ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  1. Flask API will start on:  http://localhost:5000      ║
║  2. In a second terminal run:                            ║
║     cd frontend && python3 -m http.server 8000           ║
║  3. Open in your browser: http://127.0.0.1:8000          ║
║                                                          ║
║  How to use:                                             ║
║  • Select any building in the left panel                 ║
║  • The Leaflet map shows REAL ESRI satellite imagery     ║
║  • Click "▶ RUN CV ON REAL SATELLITE IMAGE"              ║
║  • Watch the CV pipeline fetch and analyze live tiles    ║
║  • Toggle between clean and annotated (detection) views  ║
║  • Click "GENERATE SITE ANALYSIS" for AI report          ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")

# ── Start Flask ───────────────────────────────────────────
os.chdir(backend_dir)
os.execv(sys.executable, [sys.executable, "app.py"])
