from __future__ import annotations

from pathlib import Path

import pytest

from znacht.config import load_household
from znacht.domain.household import Household

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "household.example.yaml"


@pytest.fixture
def household() -> Household:
    return load_household(EXAMPLE)
