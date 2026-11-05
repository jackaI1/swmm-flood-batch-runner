import pytest
from pyswmm import Links, Simulation

from swmm_batch.hydraulics import manning_full_pipe


def test_manning_known_capacity_and_scaling():
    # Reference: A=pi/4 m², hydraulic radius=0.25 m, slope=0.001, n=0.013.
    assert manning_full_pipe(1, 0.001, 0.013) == pytest.approx(0.75818, rel=1e-4)
    assert manning_full_pipe(2, 0.001, 0.013) / manning_full_pipe(1, 0.001, 0.013) == pytest.approx(2**(8/3))


@pytest.mark.parametrize("values", [(0, 0.01, 0.013), (1, -0.1, 0.013), (1, 0.01, 0),
                                    (float("nan"), 0.01, 0.013)])
def test_manning_invalid_inputs(values):
    with pytest.raises(ValueError):
        manning_full_pipe(*values)


def test_real_swmm_matches_half_full_manning_pipe(tmp_path):
    # A half-full circle has the same hydraulic radius as a full circle and
    # half its area. Kinematic routing should recover d/D=0.5 at Q=Qfull/2.
    q = manning_full_pipe(1.0, 0.001, 0.013) / 2
    inp = tmp_path / "uniform.inp"
    inp.write_text(f"""[OPTIONS]
FLOW_UNITS CMS
FLOW_ROUTING KINWAVE
START_DATE 01/01/2025
END_DATE 01/01/2025
END_TIME 04:00:00
ROUTING_STEP 5
[JUNCTIONS]
UP 101 2
[OUTFALLS]
DOWN 100 FREE NO
[CONDUITS]
PIPE UP DOWN 1000 0.013 0 0
[XSECTIONS]
PIPE CIRCULAR 1 0 0 0 1
[INFLOWS]
UP FLOW CONSTANT FLOW 1 1
[TIMESERIES]
CONSTANT 0:00 {q:.10f}
CONSTANT 4:00 {q:.10f}
[REPORT]
CONTINUITY YES
""")
    with Simulation(str(inp)) as sim:
        pipe = Links(sim)["PIPE"]
        for _ in sim:
            depth, flow = pipe.depth, pipe.flow
        assert flow == pytest.approx(q, rel=0.01)
        assert depth == pytest.approx(0.5, abs=0.01)
