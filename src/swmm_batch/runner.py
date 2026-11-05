"""Run EPA SWMM sequentially and retain compact, joinable result tables."""

import json
import math
from pathlib import Path
import re

import geopandas as gpd
import pandas as pd
from pyswmm import Links, Nodes, Simulation

from .gis import Catchment, ISSUE_COLUMNS, load_catchment
from .model import write_model
from .storms import design_storm


def continuity_status(runoff_error_pct: float, routing_error_pct: float,
                      limit_pct: float = 1.0) -> str:
    if not math.isfinite(limit_pct) or limit_pct <= 0:
        raise ValueError("Continuity limit must be finite and positive")
    return "ok" if all(math.isfinite(x) and abs(x) <= limit_pct
                       for x in (runoff_error_pct, routing_error_pct)) else "unstable"


def run_event(catchment: Catchment, inp: Path, return_period: int,
              continuity_limit_pct: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Integrate durations at every adaptive routing step; use engine peak stats.

    Node velocity is undefined for a point, so velocity belongs to conduits.
    A conduit cannot spill independently: endpoint flooding is tracked instead.
    """
    node_results, link_results, summary = {}, {}, {}
    crowns = {}
    for row in catchment.manholes.loc[catchment.manholes.kind == "junction"].itertuples():
        diameters = catchment.pipes.loc[(catchment.pipes.from_node == row.id) |
                                        (catchment.pipes.to_node == row.id), "diameter_m"]
        crowns["N_" + row.id] = float(diameters.max())
    full_depths = {"P_" + row.id: row.diameter_m for row in catchment.pipes.itertuples()}
    full_depths.update({lid: 0.25 for lid in catchment.surface.id})
    surface_junction_ids = {"S_" + nid for nid in catchment.manholes.loc[
        catchment.manholes.kind == "junction", "id"]}
    with Simulation(str(inp), str(inp.with_suffix(".rpt")), str(inp.with_suffix(".out"))) as sim:
        nodes = {n.nodeid: n for n in Nodes(sim)}
        links = {link.linkid: link for link in Links(sim)}
        conduit_ids = {"P_" + p for p in catchment.pipes.id} | set(catchment.surface.id)
        for nid in nodes:
            node_results[nid] = {"return_period_yr": return_period, "node_id": nid,
                                 "layer": "surface" if nid.startswith("S_") else "sewer",
                                 "peak_depth_m": 0.0, "flood_duration_s": 0.0,
                                 "flood_volume_m3": 0.0, "surcharge_duration_s": 0.0,
                                 "surface_wet_duration_s": 0.0}
        for lid, link in links.items():
            link_results[lid] = {"return_period_yr": return_period, "link_id": lid,
                                 "layer": "sewer" if lid.startswith("P_") else
                                          "surface" if lid.startswith("T_") else "exchange",
                                 "peak_depth_m": 0.0, "peak_velocity_m_s": None,
                                 "peak_abs_flow_m3_s": 0.0, "full_duration_s": 0.0,
                                 "endpoint_flood_duration_s": 0.0,
                                 "reverse_flow_duration_s": 0.0,
                                 "forward_volume_m3": 0.0, "reverse_volume_m3": 0.0}

        def finished():
            # SWMM finalizes mass balance at swmm_end(), before close().
            summary.update({"return_period_yr": return_period,
                            "engine_version": sim.engine_version,
                            "runoff_error_pct": sim.runoff_error,
                            "routing_error_pct": sim.flow_routing_error})

        sim.add_after_end(finished)
        previous = sim.start_time
        steps = 0
        for _ in sim:
            now = sim.current_time
            dt = (now - previous).total_seconds()
            previous = now
            steps += 1
            flooding = {}
            for nid, node in nodes.items():
                depth, flood = node.depth, node.flooding
                result = node_results[nid]
                flooding[nid] = flood > 1e-6
                result["flood_duration_s"] += dt * flooding[nid]
                result["surcharge_duration_s"] += dt * (nid in crowns and depth > crowns[nid] + 1e-4)
                result["surface_wet_duration_s"] += dt * (nid in surface_junction_ids and depth > 0.05)
            for lid, link in links.items():
                result = link_results[lid]
                flow, depth = link.flow, link.depth
                result["peak_depth_m"] = max(result["peak_depth_m"], depth)
                result["peak_abs_flow_m3_s"] = max(result["peak_abs_flow_m3_s"], abs(flow))
                result["forward_volume_m3"] += max(flow, 0) * dt
                result["reverse_volume_m3"] += max(-flow, 0) * dt
                result["reverse_flow_duration_s"] += dt * (flow < -1e-6)
                result["endpoint_flood_duration_s"] += dt * any(flooding[nid] for nid in link.connections)
                if lid in conduit_ids:
                    result["full_duration_s"] += dt * (depth >= full_depths[lid] - 1e-4)
        elapsed = (sim.current_time - sim.start_time).total_seconds()
        end_reached = sim.current_time == sim.end_time
        # Object stats require a running engine; mass balance needs swmm_end.
        for nid, node in nodes.items():
            stats = node.statistics
            node_results[nid]["peak_depth_m"] = stats["max_depth"]
            node_results[nid]["flood_volume_m3"] = stats["flooding_volume"]
        for lid in conduit_ids:
            stats = links[lid].conduit_statistics
            link_results[lid].update(peak_depth_m=stats["peak_depth"],
                                     peak_velocity_m_s=stats["peak_velocity"],
                                     peak_abs_flow_m3_s=abs(stats["peak_flow"]))
    node_table = pd.DataFrame(node_results.values())
    link_table = pd.DataFrame(link_results.values())
    report = inp.with_suffix(".rpt").read_text()
    match = re.search(r"% of Steps Not Converging\s*:\s*([\d.]+)", report)
    nonconverging_pct = float(match.group(1)) if match else float("nan")
    summary.update({
        "status": continuity_status(summary["runoff_error_pct"], summary["routing_error_pct"],
                                     continuity_limit_pct),
        "continuity_limit_pct": continuity_limit_pct,
        "nonconverging_steps_pct": nonconverging_pct,
        "routing_steps": steps, "simulated_duration_s": elapsed,
        "completed": end_reached,
        "surcharged_nodes": int((node_table.surcharge_duration_s > 0).sum()),
        "flooded_nodes": int((node_table.flood_duration_s > 0).sum()),
        "surface_wet_nodes": int((node_table.surface_wet_duration_s > 0).sum()),
        "lost_flood_volume_m3": float(node_table.flood_volume_m3.sum()),
        "max_surface_depth_m": float(node_table.loc[node_table.layer == "surface", "peak_depth_m"].max()),
        "max_sewer_depth_m": float(node_table.loc[node_table.layer == "sewer", "peak_depth_m"].max()),
    })
    if (not end_reached or not math.isfinite(nonconverging_pct) or nonconverging_pct > 1.0
            or not all(math.isfinite(x) for x in node_table.peak_depth_m)):
        summary["status"] = "unstable"
    return node_table, link_table, summary


def export_spatial(catchment, nodes, links, path):
    base_nodes = pd.concat([
        catchment.manholes.assign(node_id=lambda f: "N_" + f.id),
        catchment.manholes.assign(node_id=lambda f: "S_" + f.id),
    ], ignore_index=True)
    base_nodes = gpd.GeoDataFrame(base_nodes, geometry="geometry", crs=catchment.manholes.crs)
    sewer = catchment.pipes.assign(link_id=lambda f: "P_" + f.id)[["link_id", "geometry"]]
    surface = catchment.surface.assign(link_id=lambda f: f.id)[["link_id", "geometry"]]
    conduits = pd.concat([sewer, surface], ignore_index=True)
    for rp in sorted(nodes.return_period_yr.unique()):
        base_nodes.merge(nodes.loc[nodes.return_period_yr == rp], on="node_id").to_file(
            path, layer=f"nodes_{rp}yr", driver="GPKG")
        conduits.merge(links.loc[links.return_period_yr == rp], on="link_id").to_file(
            path, layer=f"conduits_{rp}yr", driver="GPKG")
    catchment.surface.to_file(path, layer="surface_corridors", driver="GPKG")
    catchment.subcatchments.to_file(path, layer="subcatchments", driver="GPKG")


def run_batch(gpkg: Path, dem: Path, output: Path, return_periods=(2, 10, 100),
              routing_step_s: float = 1.0, continuity_limit_pct: float = 1.0,
              inlet_area_m2: float = 0.04) -> pd.DataFrame:
    """Write each batch into a new directory, preserving previous runs."""
    periods = tuple(return_periods)
    if not periods or len(set(periods)) != len(periods):
        raise ValueError("Choose at least one distinct return period")
    storms = [design_storm(rp) for rp in periods]
    continuity_status(0, 0, continuity_limit_pct)
    output.mkdir(parents=True, exist_ok=False)
    try:
        catchment = load_catchment(gpkg, dem)
    except Exception as exc:
        if hasattr(exc, "issues"):
            exc.issues.to_csv(output / "qa_issues.csv", index=False)
        raise
    pd.DataFrame(columns=ISSUE_COLUMNS).to_csv(output / "qa_issues.csv", index=False)
    nodes, links, summaries = [], [], []
    for rp, storm in zip(periods, storms):
        event = output / f"storm_{rp}yr"
        event.mkdir()
        storm.to_csv(event / "rainfall.csv", index=False)
        inp = write_model(catchment, storm, event / "model.inp", routing_step_s, inlet_area_m2)
        n, l, summary = run_event(catchment, inp, rp, continuity_limit_pct)
        nodes.append(n)
        links.append(l)
        summaries.append(summary)
    node_table, link_table = pd.concat(nodes, ignore_index=True), pd.concat(links, ignore_index=True)
    node_table.to_csv(output / "nodes.csv", index=False)
    link_table.to_csv(output / "links.csv", index=False)
    summary_table = pd.DataFrame(summaries)
    summary_table.to_csv(output / "summary.csv", index=False)
    export_spatial(catchment, node_table, link_table, output / "results.gpkg")
    manifest = {"input_gpkg": str(gpkg.resolve()), "input_dem": str(dem.resolve()),
                "return_periods_yr": periods, "routing_step_s": routing_step_s,
                "inlet_area_m2": inlet_area_m2, "continuity_limit_pct": continuity_limit_pct,
                "rainfall": "illustrative alternating-block IDF, not municipal design data",
                "duration_integration": "right endpoint of each native adaptive routing step"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return summary_table
