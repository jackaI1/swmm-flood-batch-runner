import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import Point

from swmm_batch.gis import InputError, load_catchment


def rewrite(gpkg, layer, change):
    data = gpd.read_file(gpkg, layer=layer)
    change(data)
    data.to_file(gpkg, layer=layer, driver="GPKG")


def test_dem_sampling_area_and_downhill_surface_routes(demo_inputs):
    model = load_catchment(*demo_inputs)
    assert model.subcatchments.area_ha.sum() == pytest.approx(2.4)
    # Nearest raster cell at the first point has x=500001, |y-y0|=1.
    assert model.manholes.rim_m.iloc[0] == pytest.approx(100.007)
    assert model.manholes.rim_m.iloc[0] - model.manholes.rim_m.iloc[-1] == pytest.approx(0.9)
    assert list(model.surface.to_node) == ["S_M2", "S_M3", "S_OUT"]
    assert np.allclose(model.surface.slope, 0.003)
    assert np.allclose(model.surface.length_m, 100)


@pytest.mark.parametrize("layer,column,value,expected", [
    ("manholes", "invert_m", np.nan, "missing_invert_m"),
    ("manholes", "invert_m", 90, "inverted_inverts"),
    ("manholes", "invert_m", 101, "invert_above_rim"),
    ("pipes", "diameter_m", 0, "zero_diameter"),
    ("pipes", "diameter_m", -1, "zero_diameter"),
    ("pipes", "roughness", 0, "invalid_roughness"),
    ("pipes", "to_node", "MISSING", "unknown_node"),
    ("subcatchments", "outlet", "MISSING", "invalid_outlet"),
    ("subcatchments", "impervious_pct", 110, "invalid_runoff_parameters"),
    ("subcatchments", "slope_pct", 0, "invalid_runoff_parameters"),
    ("manholes", "id", "bad;id", "invalid_id"),
])
def test_flags_unsafe_attributes(demo_inputs, layer, column, value, expected):
    gpkg, dem = demo_inputs
    rewrite(gpkg, layer, lambda data: data.__setitem__(column, data[column].mask(data.index == 0, value)))
    with pytest.raises(InputError) as exc:
        load_catchment(gpkg, dem)
    assert expected in set(exc.value.issues.code)


def test_disconnected_node_and_missing_schema(demo_inputs):
    gpkg, dem = demo_inputs
    rewrite(gpkg, "pipes", lambda frame: frame.drop(index=0, inplace=True))
    with pytest.raises(InputError) as exc:
        load_catchment(gpkg, dem)
    assert "disconnected_node" in set(exc.value.issues.code)
    rewrite(gpkg, "pipes", lambda frame: frame.drop(columns="diameter_m", inplace=True))
    with pytest.raises(InputError) as exc:
        load_catchment(gpkg, dem)
    assert "missing_column" in set(exc.value.issues.code)


def test_dem_nodata_is_not_an_elevation(demo_inputs):
    gpkg, dem = demo_inputs
    with rasterio.open(dem, "r+") as dataset:
        dataset.write(np.full((dataset.height, dataset.width), dataset.nodata), 1)
    with pytest.raises(InputError) as exc:
        load_catchment(gpkg, dem)
    assert "dem_nodata" in set(exc.value.issues.code)


def test_geographic_crs_rejected(demo_inputs):
    gpkg, dem = demo_inputs
    frame = gpd.read_file(gpkg, layer="manholes").to_crs(4326)
    frame.to_file(gpkg, layer="manholes", driver="GPKG")
    with pytest.raises(InputError) as exc:
        load_catchment(gpkg, dem)
    assert "metric_crs_required" in set(exc.value.issues.code)


def test_dem_extent_and_surface_sink(demo_inputs):
    gpkg, dem = demo_inputs
    with pytest.raises(InputError) as exc:
        load_catchment(gpkg, dem, max_surface_span_m=50)
    assert "surface_sink" in set(exc.value.issues.code)
    # Shift every geometry coherently: topology stays valid, raster coverage fails.
    for layer in ["manholes", "pipes", "subcatchments"]:
        rewrite(gpkg, layer, lambda data: data.__setitem__("geometry", data.geometry.translate(xoff=10000)))
    with pytest.raises(InputError) as exc:
        load_catchment(gpkg, dem)
    assert "dem_outside" in set(exc.value.issues.code)


def test_geometry_and_duplicate_ids_rejected(demo_inputs):
    gpkg, dem = demo_inputs
    rewrite(gpkg, "manholes", lambda data: data.__setitem__("id", ["M1", "M1", "M3", "OUT"]))
    with pytest.raises(InputError) as exc:
        load_catchment(gpkg, dem)
    assert "duplicate_id" in set(exc.value.issues.code)
    rewrite(gpkg, "pipes", lambda data: data.__setitem__("geometry", [Point(0, 0)] * len(data)))
    with pytest.raises(InputError) as exc:
        load_catchment(gpkg, dem)
    assert "invalid_geometry" in set(exc.value.issues.code)
