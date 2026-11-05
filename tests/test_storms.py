import numpy as np
import pytest

from swmm_batch.storms import DESIGN_DEPTHS_MM, design_storm


@pytest.mark.parametrize("period", [2, 10, 100])
def test_rainfall_conserves_design_depth_and_peaks_near_40_percent(period):
    rain = design_storm(period)
    assert len(rain) == 12
    assert rain.depth_mm.sum() == pytest.approx(DESIGN_DEPTHS_MM[period])
    assert (rain.intensity_mm_hr * rain.interval_min / 60).sum() == pytest.approx(DESIGN_DEPTHS_MM[period])
    assert rain.loc[rain.intensity_mm_hr.idxmax(), "minute"] == 20
    assert np.isfinite(rain.intensity_mm_hr).all()
    assert (rain.intensity_mm_hr > 0).all()


@pytest.mark.parametrize("kwargs", [dict(return_period=5), dict(return_period=2, interval_min=7),
                                    dict(return_period=2, duration_min=0),
                                    dict(return_period=2, peak_fraction=1)])
def test_bad_storm_parameters_fail(kwargs):
    with pytest.raises(ValueError):
        design_storm(**kwargs)
