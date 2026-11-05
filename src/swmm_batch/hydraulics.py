"""Independent SI hydraulic calculations for screening and verification."""

import math


def manning_full_pipe(diameter_m: float, slope: float, roughness: float) -> float:
    """Full circular pipe capacity (m³/s) for uniform, free gravity flow."""
    if not all(math.isfinite(x) and x > 0 for x in (diameter_m, slope, roughness)):
        raise ValueError("Diameter, slope and Manning roughness must be finite and positive")
    return math.pi * diameter_m**2 / 4 * (diameter_m / 4)**(2 / 3) * slope**0.5 / roughness
