import json
import re

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest

from swmm_batch.cli import main
from swmm_batch.gis import InputError, load_catchment
from swmm_batch.model import write_model
from swmm_batch.runner import continuity_status, run_batch, run_event
from swmm_batch.storms import design_storm


@pytest.fixture(scope="module")
def batch(tmp_path_factory):
    from swmm_batch.gis import create_demo
    directory = tmp_path_factory.mktemp("batch")
    gpkg, dem = create_demo(directory / "inputs")
    results = directory / "results"
    summary = run_batch(gpkg, dem, results)
    return gpkg, dem, results, summary


def test_three_real_storms_and_mass_balance(batch):
    _, _, output, summary = batch
    assert list(summary.return_period_yr) == [2, 10, 100]
    assert (summary.status == "ok").all()
    assert summary.completed.all()
    assert (summary.simulated_duration_s == 21600).all()
    assert (summary.routing_error_pct.abs() < 1).all()
    assert (summary.runoff_error_pct.abs() < 1).all()
    assert (summary.nonconverging_steps_pct <= 1).all()
    assert summary.iloc[2].lost_flood_volume_m3 > 100
    assert summary.iloc[0].lost_flood_volume_m3 == 0
    assert (summary.surcharged_nodes == 3).all()
    nodes, links = pd.read_csv(output / "nodes.csv"), pd.read_csv(output / "links.csv")
    assert len(nodes) == 24 and len(links) == 27
    assert not nodes.duplicated(["return_period_yr", "node_id"]).any()
    assert not links.duplicated(["return_period_yr", "link_id"]).any()
    assert set(links.layer) == {"surface", "sewer", "exchange"}
    conduits = links[links.layer != "exchange"]
    assert np.isfinite(conduits.peak_velocity_m_s).all()
    assert (conduits.peak_velocity_m_s > 0).all()
    assert nodes.flood_duration_s.max() > 500
    assert links.endpoint_flood_duration_s.max() > 500
    for rp, expected in [(2, 25), (10, 45), (100, 75)]:
        report = (output / f"storm_{rp}yr/model.rpt").read_text()
        depth = re.search(r"Total Precipitation\s*\.+\s+[\d.]+\s+([\d.]+)", report)
        assert float(depth.group(1)) == pytest.approx(expected)
        assert (output / f"storm_{rp}yr/model.out").stat().st_size > 1000


def test_qgis_layers_are_joined_and_manifest_is_readable(batch):
    _, _, output, _ = batch
    layers = set(gpd.list_layers(output / "results.gpkg").name)
    assert {"nodes_2yr", "nodes_100yr", "conduits_100yr", "subcatchments", "surface_corridors"} <= layers
    nodes = gpd.read_file(output / "results.gpkg", layer="nodes_100yr")
    assert len(nodes) == 8
    assert nodes.crs.to_epsg() == 32617
    assert nodes.flood_volume_m3.max() > 100
    assert json.loads((output / "manifest.json").read_text())["inlet_area_m2"] == 0.04


def test_smaller_timestep_preserves_flood_volume_and_peak(batch, tmp_path):
    gpkg, dem, _, base = batch
    refined = run_batch(gpkg, dem, tmp_path / "fine", (100,), routing_step_s=0.5)
    assert refined.status.iloc[0] == "ok"
    assert refined.lost_flood_volume_m3.iloc[0] == pytest.approx(base.lost_flood_volume_m3.iloc[2], rel=0.02)
    assert refined.max_sewer_depth_m.iloc[0] == pytest.approx(base.max_sewer_depth_m.iloc[2], rel=0.01)


def test_surface_sewer_exchange_reverses_under_tailwater(demo_inputs, tmp_path):
    model = load_catchment(*demo_inputs)
    inp = write_model(model, design_storm(2), tmp_path / "tailwater.inp")
    # A raised receiving-water level pushes water up from the sewer to street.
    inp.write_text(inp.read_text().replace("N_OUT 97.100000 FREE NO", "N_OUT 97.100000 FIXED 100.0 NO"))
    _, links, _ = run_event(model, inp, 2)
    exchange = links[links.layer == "exchange"]
    assert exchange.reverse_volume_m3.sum() > 1
    assert exchange.reverse_flow_duration_s.max() > 60


@pytest.mark.parametrize("runoff,routing,expected", [(0, 0, "ok"), (-0.8, 0.9, "ok"),
    (1.01, 0, "unstable"), (0, -1.01, "unstable"), (float("nan"), 0, "unstable"),
    (0, float("inf"), "unstable")])
def test_continuity_flags_both_signs_and_nonfinite(runoff, routing, expected):
    assert continuity_status(runoff, routing) == expected


def test_rejected_inputs_leave_actionable_qa_report(demo_inputs, tmp_path):
    gpkg, dem = demo_inputs
    pipes = gpd.read_file(gpkg, layer="pipes")
    pipes.loc[0, "diameter_m"] = 0
    pipes.to_file(gpkg, layer="pipes", driver="GPKG")
    output = tmp_path / "bad"
    with pytest.raises(InputError):
        run_batch(gpkg, dem, output)
    assert "zero_diameter" in set(pd.read_csv(output / "qa_issues.csv").code)
    assert not list(output.glob("storm_*"))


def test_cli_exit_codes_and_preserves_previous_outputs(batch, tmp_path, capsys):
    gpkg, dem, output, _ = batch
    assert main(["qa", "--gpkg", str(gpkg), "--dem", str(dem)]) == 0
    args = ["run", "--gpkg", str(gpkg), "--dem", str(dem), "--output", str(output)]
    assert main(args) == 1
    strict = ["run", "--gpkg", str(gpkg), "--dem", str(dem), "--output", str(tmp_path / "strict"),
              "--return-periods", "2", "--continuity-limit", "0.0001"]
    assert main(strict) == 2
    assert "unstable" in capsys.readouterr().out


def test_coarse_step_flags_nonconvergence_even_with_small_mass_error(batch, tmp_path):
    gpkg, dem, _, _ = batch
    summary = run_batch(gpkg, dem, tmp_path / "coarse", (100,), routing_step_s=5)
    assert summary.routing_error_pct.abs().iloc[0] < 1
    assert summary.nonconverging_steps_pct.iloc[0] > 1
    assert summary.status.iloc[0] == "unstable"
