# Model and output notes

## Two interacting drainage layers

I write an EPA SWMM input file for each storm. The dynamic-wave solver accounts for pressure and backwater in the underground circular pipes. The surface corridors are 4 m wide rectangular open channels with Manning n = 0.025 and a 0.25 m bank depth. Surface nodes have 200 m² of constant storage area and a 0.25 m maximum depth. These values are deliberately simple shared assumptions, not measured street cross sections.

Each sewer node has the GIS invert, a rim derived from the DEM and 10 m of permitted additional surcharge head. That pressure allowance keeps the engine from deleting sewer water at the rim before it can use the exchange opening. A bottom orifice, an opening governed by the water head on both sides, connects each surface node to its sewer junction. Its area defaults to 0.04 m², its discharge coefficient is 0.65 and it has no flap gate. Positive exchange flow means street to sewer; negative means sewer to street. The tailwater regression test raises the sewer outfall stage and verifies actual negative exchange flow. The default free-outfall demo has forward exchange only.

Rain falls on the subcatchments and runoff first enters the surface layer. I use Horton infiltration (75 to 10 mm/h, decay 4/h, 7-day drying time), impervious/pervious roughness of 0.015/0.15, and depression storage of 1/3 mm. These are fixed example assumptions. The model has no snow, groundwater, sanitary flow or water quality. With ponding disabled, water above a surface node's maximum depth is a recorded loss, not stored off-map. The saved flood volume therefore describes water leaving the represented corridor, not all water on the street.

## Rainfall and numerical controls

The illustrative depth-duration relation is `D(t) = a*t/(t+10)^0.75`, with time in minutes. I choose `a` to produce one-hour depths of 25, 45 and 75 mm. Differences of cumulative depths produce 5-minute rainfall blocks. I arrange those blocks around the 40% peak location, preserving total rain exactly. The resulting design storms are alternating-block Chicago-style approximations. I do not claim these are local intensity-duration-frequency values or exact analytical Chicago hyetographs.

SWMM receives interval-start intensities in mm/h plus an explicit zero at minute 60. Tests compare SWMM's reported total precipitation against each intended depth. Each run lasts six hours, with a maximum routing step of 1 s, adaptive step factor 0.75, minimum step 0.1 s, 12 trials and a 0.001 m head tolerance. The runoff calculation step is 30 s and the saved report step is 60 s. I run sequentially because the engine is not reentrant within a single Python process.

## Output contract

Each batch contains:

| File | Contents |
| --- | --- |
| `qa_issues.csv` | Layer, feature ID, code and explanation; empty on successful QA |
| `nodes.csv` | One row per storm and node, with layer, peak depth, overflow duration and volume, surcharge duration, and surface wet duration |
| `links.csv` | One row per storm and pipe, surface channel or exchange opening, with peak depth, absolute peak flow, conduit velocity, full duration, endpoint flooding, reverse-flow duration and directional volumes |
| `summary.csv` | Event completion, engine version, both continuity errors, nonconvergence, counts, lost flood volume and peak depths |
| `results.gpkg` | Results joined to nodes and conduits per storm, plus surface corridors and subcatchments |
| `manifest.json` | Local input paths and run parameters; generated locally, not committed |
| `storm_*yr/rainfall.csv` | Interval-start minute, intensity, depth and interval length |
| `storm_*yr/model.inp`, `.rpt`, `.out` | Reviewable input, engine report and SWMM binary output |

IDs are prefixed to separate layers: `N_` for sewer nodes, `S_` for surface nodes, `P_` for sewer pipes, `T_` for surface channels and `I_` for exchange openings. Original IDs remain in the spatial result attributes. Exchange openings have coincident endpoints and are only in the CSV, where both flow directions are recorded. Their velocity is blank because conduit velocity is not defined for these links. Node velocity is omitted for the same reason.

All depths are metres above a node invert or conduit bottom. All velocities are m/s, flow rates m³/s, volumes m³ and durations seconds. Peak conduit velocity, depth and flow and peak node depth and flood volume come from native SWMM statistics. Durations and directional exchange volumes use right-endpoint integration at every adaptive routing step. A threshold crossing can be displaced by up to one calculation step; the one-minute saved binary file does not control these durations.

`flood_duration_s` counts node overflow above 1e-6 m³/s. `surcharge_duration_s` counts sewer junction depth above the highest connected pipe crown, with a 0.1 mm tolerance. It excludes the outfalls. `surface_wet_duration_s` counts non-outfall surface node depth above 0.05 m. `full_duration_s` counts conduit depth at its full diameter or channel height, with a 0.1 mm tolerance. `endpoint_flood_duration_s` counts time when either end node overflows; a conduit does not independently lose floodwater. Node flood volumes are engine totals, including tiny flows below the duration threshold.

## Interpreting stability

I read runoff and routing continuity errors after SWMM has finalized its water balance. Their percentage errors compare water entering the system with water leaving it and changing storage. The complete volume breakdown stays in each `.rpt` file. A negative error means the accounted outflow plus final storage exceeds inflow plus initial storage. I flag either sign above the chosen absolute percentage threshold (default 1%).

I also read the engine's reported percentage of steps that did not converge and flag values above 1%, missing convergence diagnostics, incomplete events and nonfinite peak node depths. `ok` means these numerical checks passed, not that every local oscillation or modelling error has been ruled out. For example, a model can conserve water while having implausible input assumptions. The tests show that a 5 s run can have a small continuity error and still fail the convergence criterion. A 0.5 s repeat of the 100-year case checks that overflow volume changes by less than 2% and peak sewer depth by less than 1%.

Command exit codes are 0 for a numerically accepted batch or passed QA, 1 for invalid inputs/arguments or an existing output directory, and 2 for a completed batch with a flagged run. Native engine errors propagate with a nonzero exit and leave the input and report for diagnosis. I inspect those reports before interpreting any flagged outputs.

## Boundaries and references

I use this as a repeatable one-dimensional comparison, not a calibrated catchment or a construction design. It has no surveyed inlet curves, local rainfall statistics, detailed road cross sections or two-dimensional spreading over terrain. The surface algorithm selects straight downhill node corridors; it cannot trace winding streets, resolve depressions or establish flood extents. The projected horizontal CRS alone cannot validate vertical datum or survey quality.

The [EPA SWMM page](https://www.epa.gov/water-research/storm-water-management-model-swmm) links the engine and manuals. The [SWMM 5.2 manual](https://www.epa.gov/system/files/documents/2022-04/swmm-users-manual-version-5.2.pdf) describes dual drainage, orifices, open channels and continuity reports. [PySWMM's simulation reference](https://pyswmm.github.io/pyswmm/reference/simulation.html) describes engine stepping and finalized balance errors. I use simplified bidirectional orifices rather than claiming to reproduce SWMM's HEC-22 street-inlet capture model.
