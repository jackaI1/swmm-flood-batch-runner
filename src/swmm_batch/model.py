"""Write reviewable SWMM inputs from validated vectors and sampled terrain."""

from pathlib import Path

import pandas as pd

from .gis import Catchment


def write_model(catchment: Catchment, storm: pd.DataFrame, path: Path,
                routing_step_s: float = 1.0, inlet_area_m2: float = 0.04) -> Path:
    if not 0.1 <= routing_step_s <= 30 or not 0 < inlet_area_m2 <= 1:
        raise ValueError("Routing step must be 0.1..30 seconds and inlet area 0..1 m²")
    n = catchment.manholes
    junctions = n.loc[n.kind == "junction"]
    outfall = n.loc[n.kind == "outfall"].iloc[0]
    parts = []

    def section(name, lines):
        parts.append("[" + name + "]\n" + "\n".join(lines) + "\n")

    section("TITLE", ["Synthetic 2-layer drainage study; SI units; illustrative rainfall"])
    section("OPTIONS", [
        "FLOW_UNITS CMS", "INFILTRATION HORTON", "FLOW_ROUTING DYNWAVE",
        "LINK_OFFSETS DEPTH", "START_DATE 01/01/2025", "START_TIME 00:00:00",
        "REPORT_START_DATE 01/01/2025", "REPORT_START_TIME 00:00:00",
        "END_DATE 01/01/2025", "END_TIME 06:00:00", "WET_STEP 00:00:30",
        "DRY_STEP 00:01:00", f"ROUTING_STEP {routing_step_s}",
        "REPORT_STEP 00:01:00", "VARIABLE_STEP 0.75", "MINIMUM_STEP 0.1",
        "ALLOW_PONDING NO", "MIN_SURFAREA 10", "MAX_TRIALS 12", "HEAD_TOLERANCE 0.001",
    ])
    interval = int(storm.interval_min.iloc[0])
    section("RAINGAGES", [f"RAIN INTENSITY 0:{interval:02d} 1.0 TIMESERIES DESIGN"])
    rain = [f"DESIGN 01/01/2025 {int(r.minute)//60:02d}:{int(r.minute)%60:02d} {r.intensity_mm_hr:.8f}"
            for r in storm.itertuples()]
    end = int(storm.minute.iloc[-1]) + interval
    rain.append(f"DESIGN 01/01/2025 {end//60:02d}:{end%60:02d} 0")
    section("TIMESERIES", rain)
    section("SUBCATCHMENTS", [
        f"{r.id} RAIN S_{r.outlet} {r.area_ha:.8f} {r.impervious_pct} {r.width_m} {r.slope_pct} 0"
        for r in catchment.subcatchments.itertuples()])
    section("SUBAREAS", [f"{r.id} 0.015 0.15 1.0 3.0 25 OUTLET 100"
                         for r in catchment.subcatchments.itertuples()])
    section("INFILTRATION", [f"{r.id} 75 10 4 7 0" for r in catchment.subcatchments.itertuples()])
    # Sewer junctions can pressurize above the rim so exchange leaves through
    # the bidirectional inlet instead of being silently deleted at the rim.
    section("JUNCTIONS", [f"N_{r.id} {r.invert_m:.6f} {r.rim_m-r.invert_m:.6f} 0 10 0"
                          for r in junctions.itertuples()])
    section("STORAGE", [f"S_{r.id} {r.rim_m:.6f} 0.25 0 FUNCTIONAL 0 0 200 0 0"
                        for r in junctions.itertuples()])
    section("OUTFALLS", [f"N_{outfall.id} {outfall.invert_m:.6f} FREE NO",
                         f"S_{outfall.id} {outfall.rim_m:.6f} FREE NO"])
    section("CONDUITS", [f"P_{r.id} N_{r.from_node} N_{r.to_node} {r.geometry.length:.6f} {r.roughness} 0 0 0 0"
                         for r in catchment.pipes.itertuples()] +
            [f"{r.id} {r.from_node} {r.to_node} {r.length_m:.6f} 0.025 0 0 0 0"
             for r in catchment.surface.itertuples()])
    section("ORIFICES", [f"I_{r.id} S_{r.id} N_{r.id} BOTTOM 0 0.65 NO 0"
                         for r in junctions.itertuples()])
    section("XSECTIONS", [f"P_{r.id} CIRCULAR {r.diameter_m} 0 0 0 1"
                          for r in catchment.pipes.itertuples()] +
            [f"{r.id} RECT_OPEN 0.25 4 0 0 1" for r in catchment.surface.itertuples()] +
            [f"I_{r.id} RECT_CLOSED {inlet_area_m2**0.5:.8f} {inlet_area_m2**0.5:.8f} 0 0 1"
             for r in junctions.itertuples()])
    section("REPORT", ["INPUT NO", "CONTINUITY YES", "FLOWSTATS YES", "NODES ALL", "LINKS ALL"])
    section("COORDINATES", [f"{prefix}_{r.id} {r.geometry.x} {r.geometry.y}"
                            for r in n.itertuples() for prefix in ["N", "S"]])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts))
    return path
