import numpy as np

from src.metrics import RunMetrics


def test_summary_counts_and_rates():
    m = RunMetrics()
    m.init(2)
    m.e_tx[:] = [1.0, 3.0]
    m.packets[:] = [10, 30]
    m.alarms["dry"] = 3
    m.meta = {"policy": "x", "seed": 0, "nodes": 2, "tiles": 1, "days": 2.0,
              "gw": {"collisions": 0, "half_duplex_losses": 0, "dl_blocked_duty": 0},
              "backhaul_bytes": 0, "backhaul_bad_frac": 0.0, "fog_bytes": 0,
              "busy": {"edge": 0.0, "fog": 0.0, "cloud": 0.0}}
    base = dict(kind="verify", tier="edge", origin=0.0, arrival=0.0, deadline=10.0, t_start=0.0,
                t_done=1.0, forced=False, pulls=0, status0=None, zone=0, ev="dry")
    m.tasks = [dict(base, t_delivered=1.0, decision=True, truth=True, truth_margin=0.3),
               dict(base, t_delivered=20.0, decision=False, truth=True, truth_margin=0.1)]
    s = m.summary()
    assert s["energy_J_node_day"] == 1.0          # (1+3)/2 nodes / 2 days
    assert s["packets_node_day"] == 10.0
    assert s["verify_accuracy"] == 0.5
    assert s["urgent_soil_success"] == 1 / 3       # one on-time decision, three alarms raised
    assert s["verify_hard_accuracy"] == 0.0
    assert np.isclose(s["missed_actuation_rate"], 0.5)
