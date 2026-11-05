import pytest

from swmm_batch.gis import create_demo


@pytest.fixture
def demo_inputs(tmp_path):
    return create_demo(tmp_path / "inputs")
