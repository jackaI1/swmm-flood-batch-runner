I built a stormwater comparison tool because I wanted to see where water goes when an underground drain cannot keep up with rain. I can run several storms against the same small neighbourhood, check which pipes fill up, and map where water collects on the street.

The example is a made-up 2.4-hectare catchment, about the area of three football fields. It has three underground pipes and three surface channels. Water can enter the sewer from the street or come back up when the sewer is under pressure. I use synthetic inputs so the whole example can be reproduced without downloading municipal data.

## Try it

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, run these commands on macOS or Linux. uv installs Python 3.11 and the packages the model needs.

```sh
git clone https://github.com/jackaI1/swmm-flood-batch-runner.git
cd swmm-flood-batch-runner
uv sync --python 3.11 --frozen --extra test
uv run python scripts/repair_macos_swmm.py
uv run swmm-batch demo --workdir outputs/demo
```

I open `outputs/demo/results/summary.csv` for the storm comparison, or drag `results.gpkg` into QGIS, a free mapping program, to see the results on a map. Each run also saves its rainfall, model input and engine report. A new run needs a new output directory so I do not overwrite earlier results.

## What I get back

The included example uses illustrative 2-, 10- and 100-year storms. Those labels describe increasing rainfall severity here, rather than a forecast or a local design standard. These are example results from EPA SWMM 5.2.4:

| Storm | Rain in one hour | Highest street depth | Water lost beyond the model | Routing balance error |
| --- | ---: | ---: | ---: | ---: |
| 2-year | 25 mm | 0.122 m | 0 m³ | -0.217% |
| 10-year | 45 mm | 0.213 m | 0 m³ | -0.120% |
| 100-year | 75 mm | 0.250 m | 167.6 m³ | -0.070% |

In the largest storm, one surface node overflows for about 580 seconds. All three sewer junctions surcharge, meaning water rises above the tops of their connected pipes. Water already travelling through the surface channels is tracked separately from overflow that leaves the model. The surface nodes have a 0.25 m overflow limit, so their depth stops increasing when water spills out of the represented system.

I keep [small example tables](examples/) in the repository. The command regenerates the complete tables and map layers.

## Look at the results in QGIS

1. Drag `outputs/demo/inputs/dem.tif` into QGIS. This is the DEM, a grid of ground elevations.
2. Drag `outputs/demo/results/results.gpkg` into the same window. Select `surface_corridors`, `subcatchments`, `nodes_100yr` and `conduits_100yr`.
3. Open the node layer's attribute table. Filter with `"layer" = 'surface'` to separate street points from sewer points at the same coordinates.
4. In Layer Properties, choose Symbology, then Graduated. Use `peak_depth_m` for depth or `flood_duration_s` for overflow duration. For conduits, use `peak_velocity_m_s` to colour by water speed.
5. Add `nodes_2yr` or `conduits_2yr` to compare with a smaller storm. The results are already joined to their geometry; no manual CSV join is needed.

The coordinates and elevations are synthetic, even though the files use a real coordinate system. They do not describe the actual location where QGIS places them.

## Use my own inputs

I can supply a GeoPackage containing `manholes`, `pipes` and `subcatchments`, together with a DEM in the same projected coordinate system with metre units. The required columns and restrictions are in [the input guide](docs/inputs.md).

```sh
uv run swmm-batch qa --gpkg catchment.gpkg --dem dem.tif
uv run swmm-batch run --gpkg catchment.gpkg --dem dem.tif \
  --output outputs/comparison --return-periods 2 10 100
```

The checks reject missing or uphill pipe inverts, nonpositive diameters, disconnected manholes, mismatched line endpoints, invalid geometry and missing terrain data. An invert is the elevation of the bottom of a pipe. When validation fails, `qa_issues.csv` identifies the affected feature before any storm runs.

I can compare inlet sizes with `--inlet-area 0.02`, in square metres, or refine the maximum calculation step with `--routing-step 0.5`, in seconds. Smaller openings limit how much water can enter or leave the sewer. The model uses a fixed street width and simplified surface storage; it is intended for reproducible comparisons, not site-specific drainage design.

## How the model works

I read the map layers with GeoPandas and sample the elevation raster with rasterio. Each manhole gets a ground elevation from the DEM. For each surface node, I choose the steepest downhill connection to another node within 150 m and check the entire straight corridor at roughly one-metre spacing. The DEM determines its direction, end elevations and slope. This is a set of one-dimensional surface routes, not a two-dimensional flood map or a complete terrain flow-path extractor.

I generate alternating rainfall blocks from an illustrative intensity-duration curve. The high-intensity blocks sit near 40% of the event duration, making a Chicago-style approximation rather than an exact Chicago storm. I send runoff to the surface layer, connect it to the sewer with bidirectional openings, and let EPA SWMM solve the water movement through PySWMM, its Python interface. Each storm includes five hours after the rain to let the network drain.

I extract peak depth and velocity from the engine's statistics. Duration and exchange-volume calculations use every internal routing step, rather than the one-minute saved report interval. Nodes are points and do not have a meaningful velocity; speed is reported for conduits. A conduit has no separate overflow outlet, so its table records flooding at either endpoint. [The model notes](docs/model.md) explain units, assumptions and the output columns.

## Checks I run

```sh
uv run pytest -q
```

The 43 tests include a known Manning pipe capacity, a real engine run that recovers the predicted half-full pipe depth, bad GIS and DEM inputs, rainfall totals, three design storms, sewer-to-street backflow, map export and a smaller-timestep comparison. The latter changes the largest storm's overflow volume by less than 2%.

I flag a run as unstable if either water-balance error exceeds 1%, more than 1% of routing steps fail to converge, the run stops early, or node depths are nonfinite. The command exits with code 2 for flagged batches and preserves the outputs for inspection. Passing these checks does not prove that a model is calibrated or suitable for engineering design.

[GitHub Actions](.github/workflows/tests.yml) runs the tests and the full demo on Linux and macOS, then saves the generated GIS files and engine reports as downloadable artifacts. The repository started with just a project description; this is its first executable workflow. I pin the engine and lock the other dependencies for repeatable runs. On some Apple Silicon wheels, the bundled native libraries have invalid signatures. The explicit repair command checks and signs private copies of only those installed libraries; it does nothing on Linux.
