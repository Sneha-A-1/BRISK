import numpy as np

from src.network_model import GELink, lora_toa
from src.resource_scheduler import Tier
from src.retrieval import Replica, classify_member, must_send, tolerance, zone_status
from src.task_model import Task, URGENT, STRATEGIC


def test_lora_toa_matches_semtech_formula():
    # SF9/125 kHz/CR4/5, 8-symbol preamble, explicit header, CRC on, 36-byte payload:
    # Ts = 4.096 ms; n_payload = 8 + ceil((288-36+28+16)/36)*5 = 53 symbols
    assert abs(lora_toa(36, 9) - (12.25 + 53) * 0.004096) < 1e-9
    # SF12 enables LowDataRateOptimize (DE=1)
    assert lora_toa(13, 12) > lora_toa(13, 9)


def test_gilbert_elliott_stationary_loss():
    rng = np.random.default_rng(1)
    link = GELink(0.1, 0.4, 600.0, rng)
    bad = [link.is_bad(t * 600.0) for t in range(1, 40000)]
    assert abs(np.mean(bad) - link.q_gb / (link.q_gb + link.q_bg)) < 0.02


def test_send_on_delta_and_availability_change():
    ref = np.array([0.2] * 5 + [10.0] * 5)
    eps = np.array([0.005] * 5 + [0.5] * 5)
    x = ref.copy()
    assert not must_send(x, ref, eps)
    x[0] += 0.006
    assert must_send(x, ref, eps)
    y = ref.copy()
    y[3] = np.nan
    assert must_send(y, ref, eps)


def test_proximity_tolerance_shrinks_near_threshold():
    rc = dict(eps_vw_max=0.01, eps_vw_min=0.002, eps_t=0.5, prox_r0=0.005, prox_r=0.03,
              eps_vw_cap=0.03, eps_t_cap=2.0, eq_kappa=4.0, eps_vw_fixed=0.005)
    pol = {"retrieval": "brisk", "proximity": True, "energy_queue": False}
    near = tolerance(pol, rc, 0.151, 0.15, 0.40, False, 0.0, 1.0)[0]
    far = tolerance(pol, rc, 0.30, 0.15, 0.40, False, 0.0, 1.0)[0]
    assert near == rc["eps_vw_min"] and far == rc["eps_vw_max"]


def test_interval_quorum_logic():
    assert zone_status(["yes", "yes", "yes", "no"], 0.5)[0] == "pos"
    assert zone_status(["no", "no", "no", "unc"], 0.5)[0] == "neg"
    assert zone_status(["yes", "unc", "no", "no"], 0.5)[0] == "inc"
    rep = Replica(2)
    rep.update(0, 1, np.array([0.14] + [0.2] * 4 + [10.0] * 5), np.array([0.005] * 10), 0.0, 3600)
    rep.t_next[0] = 100.0
    pol = {"retrieval": "sod_fixed", "validity": "heartbeat"}
    # exact until the node's next sample
    assert classify_member(pol, rep, 0, 0.142, "dry", 50.0, 21600, 3600) == "yes"
    # afterwards the +-eps band straddles the threshold -> uncertain
    assert classify_member(pol, rep, 0, 0.142, "dry", 200.0, 21600, 3600) == "unc"
    # silent beyond the heartbeat -> uncertain
    assert classify_member(pol, rep, 0, 0.20, "dry", 30000.0, 21600, 3600) == "unc"


class _Eng:
    def __init__(self):
        self.ev = []

    def schedule(self, t, kind, data):
        self.ev.append((t, kind, data))


def test_preemptive_edf_tier():
    tier = Tier("edge", 1, 1.0, "edf")
    tier.engine = _Eng()
    s = Task("map", 0.0, 1000.0, 10.0, 0, 0, STRATEGIC)
    tier.submit(0.0, s)
    u = Task("verify", 1.0, 5.0, 0.5, 0, 0, URGENT)
    tier.submit(1.0, u)
    assert tier.running[0] is u          # urgent preempted the strategic task
    assert abs(s.remaining - 9.0) < 1e-9  # 1 s of work was done before preemption
    t_done, _, (tr, task, ver) = tier.engine.ev[-1]
    assert task is u and abs(t_done - 1.5) < 1e-9
    assert tier.complete(1.5, u, ver)
    assert tier.running[0] is s           # strategic task resumed
