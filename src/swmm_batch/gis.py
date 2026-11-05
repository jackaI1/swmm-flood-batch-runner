"""Synthetic inputs, GIS QA, and surface corridors inferred from DEM samples."""

from dataclasses import dataclass
from pathlib import Path
import re

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

ISSUE_COLUMNS = ["layer", "feature_id", "code", "message"]
SCHEMA = {
    "manholes": ["id", "kind", "invert_m"],
    "pipes": ["id", "from_node", "to_node", "diameter_m", "roughness"],
    "subcatchments": ["id", "outlet", "impervious_pct", "width_m", "slope_pct"],
}


class InputError(ValueError):
    def __init__(self, issues):
        self.issues = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
        super().__init__("Input QA failed: " + "; ".join(self.issues.code.unique()))


@dataclass
class Catchment:
    manholes: gpd.GeoDataFrame
    pipes: gpd.GeoDataFrame
    subcatchments: gpd.GeoDataFrame
    surface: gpd.GeoDataFrame


def create_demo(directory: Path) -> tuple[Path, Path]:
    """Create a wholly synthetic 2.4 ha catchment and 2 m DEM in metre units."""
    directory.mkdir(parents=True, exist_ok=True)
    gpkg, dem = directory / "catchment.gpkg", directory / "dem.tif"
    if gpkg.exists() or dem.exists():
        raise FileExistsError("Demo inputs already exist; choose a new directory")
    crs = "EPSG:32617"
    points = [Point(500000 + 100 * i, 4800000) for i in range(4)]
    manholes = gpd.GeoDataFrame({
        "id": ["M1", "M2", "M3", "OUT"],
        "kind": ["junction"] * 3 + ["outfall"],
        "invert_m": [98.0, 97.7, 97.4, 97.1],
    }, geometry=points, crs=crs)
    pipes = gpd.GeoDataFrame({
        "id": ["P1", "P2", "P3"], "from_node": ["M1", "M2", "M3"],
        "to_node": ["M2", "M3", "OUT"], "diameter_m": [0.3, 0.3, 0.25],
        "roughness": [0.013] * 3,
    }, geometry=[LineString(points[i:i + 2]) for i in range(3)], crs=crs)
    subcatchments = gpd.GeoDataFrame({
        "id": ["C1", "C2", "C3"], "outlet": ["M1", "M2", "M3"],
        "impervious_pct": [85.0] * 3, "width_m": [80.0] * 3,
        "slope_pct": [1.0] * 3,
    }, geometry=[box(499960 + 100 * i, 4799950, 500040 + 100 * i, 4800050)
                 for i in range(3)], crs=crs)
    for layer, frame in zip(SCHEMA, [manholes, pipes, subcatchments]):
        frame.to_file(gpkg, layer=layer, driver="GPKG")
    transform = from_origin(499930, 4800070, 2, 2)
    rows, cols = np.indices((70, 220))
    x, y = rasterio.transform.xy(transform, rows, cols)
    elevation = 100 - 0.003 * (np.asarray(x) - 500000) + 0.01 * abs(np.asarray(y) - 4800000)
    with rasterio.open(dem, "w", driver="GTiff", height=70, width=220,
                       count=1, dtype="float64", crs=crs, transform=transform,
                       nodata=-9999.0) as dataset:
        dataset.write(elevation.reshape(70, 220), 1)
    return gpkg, dem


def load_catchment(gpkg: Path, dem: Path, max_surface_span_m: float = 150) -> Catchment:
    """Fail before SWMM if geometry, topology, attributes or terrain are unsafe."""
    issues = []

    def flag(layer, feature, code, message):
        issues.append([layer, str(feature), code, message])

    frames = {}
    for layer, columns in SCHEMA.items():
        try:
            frame = gpd.read_file(gpkg, layer=layer)
        except Exception as exc:
            flag(layer, "*", "unreadable_layer", str(exc))
            continue
        frames[layer] = frame
        for column in columns:
            if column not in frame:
                flag(layer, "*", "missing_column", column)
        if frame.empty:
            flag(layer, "*", "empty_layer", "At least one feature is required")
        if (frame.crs is None or not frame.crs.is_projected or
                any(axis.unit_name != "metre" for axis in frame.crs.axis_info)):
            flag(layer, "*", "metric_crs_required", "Use a projected CRS with metre axes")
        for i, row in frame.iterrows():
            fid = row.get("id", i)
            if not isinstance(fid, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,24}", fid):
                flag(layer, fid, "invalid_id", "Use a letter followed by letters, digits or underscores")
            geom = row.geometry
            expected = {"manholes": {"Point"}, "pipes": {"LineString"},
                        "subcatchments": {"Polygon", "MultiPolygon"}}[layer]
            if geom is None or geom.is_empty or not geom.is_valid or geom.geom_type not in expected:
                flag(layer, fid, "invalid_geometry", "Check geometry type, validity and emptiness")
        if "id" in frame and frame.id.duplicated().any():
            flag(layer, "*", "duplicate_id", "IDs must be unique within each layer")
    if issues:
        raise InputError(issues)
    nodes, pipes, subs = (frames[key].copy() for key in SCHEMA)
    if not (nodes.crs == pipes.crs == subs.crs):
        flag("all", "*", "crs_mismatch", "Vector layers must use the same CRS")

    for layer, frame, columns in [
        ("manholes", nodes, ["invert_m"]),
        ("pipes", pipes, ["diameter_m", "roughness"]),
        ("subcatchments", subs, ["impervious_pct", "width_m", "slope_pct"]),
    ]:
        for col in columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
            for fid in frame.loc[~np.isfinite(frame[col]), "id"]:
                flag(layer, fid, "missing_" + col, "A finite numeric value is required")
    for row in nodes.itertuples():
        if row.kind not in {"junction", "outfall"}:
            flag("manholes", row.id, "invalid_kind", "Use junction or outfall")
    if sum(nodes.kind == "outfall") != 1:
        flag("manholes", "*", "outfall_count", "This workflow requires exactly one outfall")
    indexed = nodes.set_index("id")
    adjacency = {node: set() for node in nodes.id}
    for row in pipes.itertuples():
        if not row.diameter_m > 0:
            flag("pipes", row.id, "zero_diameter", "Diameter must be positive")
        if not row.roughness > 0:
            flag("pipes", row.id, "invalid_roughness", "Manning n must be positive")
        if row.geometry.length <= 0:
            flag("pipes", row.id, "zero_length", "Pipe length must be positive")
        if row.from_node not in indexed.index or row.to_node not in indexed.index:
            flag("pipes", row.id, "unknown_node", "Endpoint references a missing manhole")
            continue
        if row.from_node == row.to_node:
            flag("pipes", row.id, "self_loop", "Pipe endpoints must differ")
        if indexed.loc[row.from_node].invert_m <= indexed.loc[row.to_node].invert_m:
            flag("pipes", row.id, "inverted_inverts", "Upstream invert must be above downstream invert")
        for endpoint, node in [(row.geometry.coords[0], row.from_node),
                               (row.geometry.coords[-1], row.to_node)]:
            if Point(endpoint).distance(indexed.loc[node].geometry) > 1:
                flag("pipes", row.id, "endpoint_mismatch", "Line endpoint is more than 1 m from its node")
        adjacency[row.from_node].add(row.to_node)
        adjacency[row.to_node].add(row.from_node)
    outfalls = list(nodes.loc[nodes.kind == "outfall", "id"])
    reached, pending = set(), outfalls.copy()
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(adjacency[node] - reached)
    for node in set(nodes.id) - reached:
        flag("manholes", node, "disconnected_node", "No pipe path to the outfall")
    for row in subs.itertuples():
        if row.outlet not in indexed.index or (row.outlet in indexed.index and
                                              indexed.loc[row.outlet].kind != "junction"):
            flag("subcatchments", row.id, "invalid_outlet", "Use a known junction ID")
        if not 0 <= row.impervious_pct <= 100 or not row.width_m > 0 or not row.slope_pct > 0:
            flag("subcatchments", row.id, "invalid_runoff_parameters", "Check impervious %, width and slope")
        if row.geometry.area <= 0:
            flag("subcatchments", row.id, "zero_area", "Area must be positive")
    if issues:
        raise InputError(issues)

    with rasterio.open(dem) as dataset:
        if dataset.crs != nodes.crs:
            flag("dem", "*", "crs_mismatch", "DEM and vector layers must share a CRS")
            raise InputError(issues)

        def sample(points, fid):
            values = []
            for point in points:
                if not (dataset.bounds.left <= point.x < dataset.bounds.right and
                        dataset.bounds.bottom < point.y <= dataset.bounds.top):
                    flag("dem", fid, "dem_outside", "A sample falls outside the raster")
                    values.append(np.nan)
                    continue
                value = next(dataset.sample([(point.x, point.y)], masked=True))[0]
                if np.ma.is_masked(value) or not np.isfinite(value):
                    flag("dem", fid, "dem_nodata", "A sample has no finite elevation")
                    values.append(np.nan)
                else:
                    values.append(float(value))
            return np.asarray(values)

        nodes["rim_m"] = sample(list(nodes.geometry), "nodes")
        for row in nodes.itertuples():
            if row.invert_m >= row.rim_m:
                flag("manholes", row.id, "invert_above_rim", "Invert must be below DEM rim")
        if issues:
            raise InputError(issues)
        corridors = []
        for row in nodes.loc[nodes.kind == "junction"].itertuples():
            candidates = nodes.loc[(nodes.rim_m < row.rim_m) & (nodes.id != row.id)].copy()
            candidates["distance_m"] = candidates.geometry.distance(row.geometry)
            candidates = candidates.loc[(candidates.distance_m > 0) &
                                         (candidates.distance_m <= max_surface_span_m)]
            if candidates.empty:
                flag("surface", row.id, "surface_sink", "No lower node within surface search distance")
                continue
            candidates["gradient"] = (row.rim_m - candidates.rim_m) / candidates.distance_m
            target = candidates.sort_values(["gradient", "id"], ascending=[False, True]).iloc[0]
            line = LineString([row.geometry, target.geometry])
            distances = np.linspace(0, line.length, max(2, int(np.ceil(line.length)) + 1))
            profile = sample([line.interpolate(d) for d in distances], row.id)
            if (np.diff(profile) > 0.025).any():
                flag("surface", row.id, "adverse_surface_profile", "Corridor crosses an uphill DEM cell; supply closer nodes")
            corridors.append({"id": "T_" + row.id, "from_node": "S_" + row.id,
                              "to_node": "S_" + target.id, "length_m": line.length,
                              "from_elevation_m": row.rim_m,
                              "to_elevation_m": target.rim_m,
                              "slope": target.gradient, "geometry": line})
    if issues:
        raise InputError(issues)
    subs["area_ha"] = subs.geometry.area / 10000
    surface = gpd.GeoDataFrame(corridors, geometry="geometry", crs=nodes.crs)
    return Catchment(nodes, pipes, subs, surface)
