I merged this into my existing [borehole-log-gis project](https://github.com/jackaI1/borehole-log-gis/tree/main/projects/swmm-flood-batch-runner). The current code is in `projects/swmm-flood-batch-runner/` there. I kept the code here so older links still work.

The move keeps the original layout, including `tests/conftest.py`, `tests/test_storms.py`, `tests/test_hydraulics.py`, `tests/test_runner.py`. I replaced the README with the report below and left out Git history, installed dependencies, caches and generated build output from the hub copy.

The project checks are configured in the hub at `.github/workflows/swmm-flood-batch-runner-tests.yml`, with commands run from this project folder and changes filtered to its paths.

---

# swmm-flood-batch-runner

I built a stormwater comparison tool to learn how the underlying idea works. This is a learning project.

## Try it

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, run these commands on macOS or Linux. uv installs Python 3.11 and the packages the model needs.

```sh
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

## Tests and limits

There are 5 test source files in this copy. No test pass count is claimed here: I have not re-run the project suite as part of this move. This is a source snapshot, and running it on a new machine may need environment-specific setup.


Project checks run from this directory through the path-filtered hub workflows: `swmm-flood-batch-runner-tests.yml`.
