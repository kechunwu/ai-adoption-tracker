from pathlib import Path

import streamlit as st

from app_lib.style import footer

st.set_page_config(page_title="Methodology · AI Adoption Tracker", page_icon="📈", layout="wide")
ROOT = Path(__file__).resolve().parent.parent
md = (ROOT / "docs" / "METHODOLOGY.md").read_text()
# links to repo files don't resolve inside the app; point them at GitHub
md = md.replace("](../", "](https://github.com/KC31415/ai-adoption-tracker/blob/main/").replace(
    "](null_calibration.md)", "](https://github.com/KC31415/ai-adoption-tracker/blob/main/docs/null_calibration.md)")
st.markdown(md)
cal = ROOT / "docs" / "null_calibration.md"
if cal.exists():
    with st.expander("Null calibration table"):
        st.markdown(cal.read_text())
footer()
