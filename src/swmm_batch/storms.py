"""Illustrative IDF-derived alternating blocks, not local regulatory rainfall."""

import math

import numpy as np
import pandas as pd

DESIGN_DEPTHS_MM = {2: 25.0, 10: 45.0, 100: 75.0}


def design_storm(return_period: int, duration_min: int = 60,
                 interval_min: int = 5, peak_fraction: float = 0.4) -> pd.DataFrame:
    """Arrange increments of an IDF depth curve around a specified peak.

    D(t) = a*t/(t+10)^0.75, calibrated to an illustrative 60-minute
    depth for each return period. Blocks are interval-start intensities.
    This is an alternating-block approximation to a Chicago-style storm.
    """
    if return_period not in DESIGN_DEPTHS_MM:
        raise ValueError("Return period must be 2, 10 or 100 years")
    if (duration_min <= 0 or interval_min <= 0 or duration_min % interval_min
            or not 0 < peak_fraction < 1):
        raise ValueError("Require positive divisible durations and 0 < peak_fraction < 1")
    t = np.arange(0, duration_min + interval_min, interval_min, dtype=float)
    a = DESIGN_DEPTHS_MM[return_period] * 70**0.75 / 60
    depths = a * t / (t + 10)**0.75
    blocks = np.sort(np.diff(depths))[::-1]
    n = len(blocks)
    peak = min(n - 1, math.floor(n * peak_fraction))
    # Place high intensities near the peak; ties go to the earlier block.
    slots = sorted(range(n), key=lambda i: (abs(i - peak), i))
    arranged = np.zeros(n)
    arranged[slots] = blocks
    return pd.DataFrame({"return_period_yr": return_period,
                         "minute": t[:-1].astype(int),
                         "intensity_mm_hr": arranged * 60 / interval_min,
                         "depth_mm": arranged,
                         "interval_min": interval_min})
