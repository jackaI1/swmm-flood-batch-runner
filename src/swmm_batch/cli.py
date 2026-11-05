"""Command line entry point with nonzero exits for rejected or unstable batches."""

import argparse
from pathlib import Path

from .gis import InputError, create_demo, load_catchment


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check GIS inputs and compare dual-drainage design storms")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Create synthetic inputs and run 2, 10 and 100 year storms")
    demo.add_argument("--workdir", type=Path, default=Path("outputs/demo"))
    qa = commands.add_parser("qa", help="Validate inputs without running EPA SWMM")
    run = commands.add_parser("run", help="Run storms using existing GIS and DEM inputs")
    for cmd in [qa, run]:
        cmd.add_argument("--gpkg", type=Path, required=True)
        cmd.add_argument("--dem", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--return-periods", type=int, nargs="+", default=[2, 10, 100])
    for cmd in [demo, run]:
        cmd.add_argument("--routing-step", type=float, default=1.0, help="Maximum routing step, seconds")
        cmd.add_argument("--continuity-limit", type=float, default=1.0, help="Maximum absolute mass error, percent")
        cmd.add_argument("--inlet-area", type=float, default=0.04, help="Area of each surface/sewer opening, m²")
    args = parser.parse_args(argv)
    try:
        if args.command == "qa":
            model = load_catchment(args.gpkg, args.dem)
            print(f"QA passed: {len(model.manholes)} nodes, {len(model.pipes)} pipes, "
                  f"{len(model.surface)} DEM-derived surface corridors")
            return 0
        from .runner import run_batch
        if args.command == "demo":
            gpkg, dem = create_demo(args.workdir / "inputs")
            output, periods = args.workdir / "results", (2, 10, 100)
        else:
            gpkg, dem, output, periods = args.gpkg, args.dem, args.output, args.return_periods
        summary = run_batch(gpkg, dem, output, periods, args.routing_step,
                            args.continuity_limit, args.inlet_area)
        print(summary[["return_period_yr", "status", "routing_error_pct", "max_surface_depth_m",
                       "surcharged_nodes", "flooded_nodes"]].to_string(index=False))
        print(f"Outputs: {output}")
        return 0 if (summary.status == "ok").all() else 2
    except (InputError, ValueError, FileExistsError) as exc:
        if isinstance(exc, InputError):
            print(exc.issues.to_string(index=False))
        else:
            print(f"Cannot run: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
