"""Local Streamlit app helpers. Puts the repo root on sys.path so `tracker` imports work."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
