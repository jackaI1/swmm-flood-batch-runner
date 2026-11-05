# Input contract

I use a single GeoPackage and a single-band elevation GeoTIFF. All coordinates, elevations and dimensions must use metres in one shared projected CRS. The tool checks the CRS but cannot detect an incorrect vertical datum. Elevations must share a datum. Valid IDs start with a letter, contain only letters, digits and underscores, and are at most 25 characters. IDs must be unique within each layer.

| Layer | Geometry | Required columns |
| --- | --- | --- |
| `manholes` | Point | `id`, `kind` (`junction` or `outfall`), `invert_m` |
| `pipes` | LineString | `id`, `from_node`, `to_node`, `diameter_m`, `roughness` (Manning n) |
| `subcatchments` | Polygon or MultiPolygon | `id`, `outlet` (junction ID), `impervious_pct`, `width_m`, `slope_pct` |

The workflow currently supports exactly one receiving outfall, with a free sewer outlet and a free surface outlet at that location. All manholes need a pipe path to it. Pipe lines must start within 1 m of their `from_node` and end within 1 m of their `to_node`. Each pipe must have a positive length, diameter and roughness. The upstream invert must be strictly higher than the downstream invert. Adverse-slope pipes can be modelled by SWMM itself, but I reject them here so a likely input mistake is not silently accepted.

Subcatchment area is calculated from the polygon, in hectares. The input slope is a percentage, not a fraction; `1.0` means 1%. Width is SWMM's effective overland flow width, rather than a polygon bounding-box dimension. The outlet names the manhole paired with the surface point receiving runoff. Impervious percentage must be between 0 and 100. Width and slope must be positive. The polygon area is used for runoff, so overlapping polygons would double-count land: I check those manually in QGIS before using real inputs.

DEM samples must be finite, within the raster and outside nodata cells. The rim is sampled from the cell containing the manhole, with nearest-cell sampling. Each pipe invert must sit below that rim. Every junction must have a lower node within 150 m. The steepest candidate corridor is sampled at no more than 1 m spacing and rejected if a sample rises by more than 0.025 m. That small allowance prevents harmless cell-edge noise from rejecting the planar synthetic raster. It is not permission to route across a real terrain barrier. A flat area, depression or winding street needs extra surface nodes or a more detailed model.

`swmm-batch qa` prints feature IDs and issue codes and exits 1 on invalid input. `swmm-batch run` also writes `qa_issues.csv` in its new output directory. A valid batch writes an empty table with column headers. Output directories must not already exist. Storm choices are 2, 10 and 100 years, with at least one distinct choice.

For the synthetic example, I set the CRS to EPSG:32617, use a 2 m DEM, three 0.8 ha polygons, 100 m pipes and a downstream pipe diameter of 0.25 m. The other pipes are 0.30 m. No municipal records, addresses or private data are included.
