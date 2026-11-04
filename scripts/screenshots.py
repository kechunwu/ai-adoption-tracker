"""Capture README screenshots of the running app with Playwright.

Usage: streamlit run streamlit_app.py --server.port 8599 &  then
       python scripts/screenshots.py http://localhost:8599
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8599"
OUT = Path(__file__).resolve().parent.parent / "docs" / "img"
PAGES = {"home": "", "tool_trends": "Tool_trends", "ai_sdk_share": "AI_SDK_share",
         "lead_lag": "Lead_lag_study"}

OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=2)
    for name, path in PAGES.items():
        pg.goto(f"{BASE}/{path}", wait_until="networkidle")
        pg.wait_for_selector("[data-testid='stAppViewContainer']")
        time.sleep(6)  # let plotly finish rendering
        pg.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
        print("saved", name)
    b.close()
