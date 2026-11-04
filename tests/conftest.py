import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name):
        return json.loads((FIX / name).read_text())
    return _load
