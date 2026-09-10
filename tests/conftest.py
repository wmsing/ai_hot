"""Pytest 公共 fixtures。"""

import pytest


@pytest.fixture
def sample_data() -> dict[str, str]:
    return {"status": "ok"}
