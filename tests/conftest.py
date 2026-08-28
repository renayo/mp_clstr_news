import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpclstr import config as C  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return C.load_config()


@pytest.fixture(scope="session")
def names():
    return C.verified_names()
