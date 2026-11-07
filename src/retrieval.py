"""Retrieval-side mechanisms: tolerance (suppression) policies, the gateway replica
with error intervals, and zone-level decision verification.

Notation (paper Sec. 3-5):
  x_i(t)      raw observation vector of node i (10 channels)
  r_i         reference vector last transmitted by node i (shared node/gateway state)
  eps_i       per-channel tolerance in force when r_i was sent
  Suppression guarantee: while node i stays silent, |x_i,c - r_i,c| <= eps_i,c for every
  channel c, *provided no packet of node i was lost* (heartbeats every H_hb bound the
  time a loss can stay undetected).
"""
from __future__ import annotations

import numpy as np

from .data_loading import VW30

N_CH = 10
VW_CH = slice(0, 5)
T_CH = slice(5, 10)


def range_filter(x: np.ndarray) -> np.ndarray:
    """Node-side physical-range check applied by every policy (VW in [0,0.6] m3/m3,
    T in [-40, 60] C, as in the CAF quality-control rules)."""
    y = x.astype(float).copy()
    vw = y[VW_CH]
    vw[(vw < 0) | (vw > 0.6)] = np.nan
    t = y[T_CH]
    t[(t < -40) | (t > 60)] = np.nan
    return y


def tolerance(policy: dict, rcfg: dict, x30: float, th_dry: float, th_wet: float,
              watch: bool, q_energy: float, e_budget: float) -> np.ndarray:
    """Per-channel tolerance vector eps for the next suppression interval."""
    kind = policy["retrieval"]
    eps = np.empty(N_CH)
    if kind == "sod_fixed":
        eps[VW_CH] = policy.get("eps_vw", rcfg["eps_vw_fixed"])
        eps[T_CH] = rcfg["eps_t"]
        return eps
    # --- BRISK: urgency-proximity tolerance allocation -------------------------
    eps[VW_CH] = rcfg["eps_vw_max"]
    eps[T_CH] = rcfg["eps_t"]
    if policy.get("proximity", True) and np.isfinite(x30):
        d = min(abs(x30 - th_dry), abs(x30 - th_wet))
        frac = np.clip((d - rcfg["prox_r0"]) / rcfg["prox_r"], 0.0, 1.0)
        eps[VW30] = rcfg["eps_vw_min"] + (rcfg["eps_vw_max"] - rcfg["eps_vw_min"]) * frac
    if watch and policy.get("watch_tighten", True):
        eps[VW30] = rcfg["eps_vw_min"]
    if policy.get("energy_queue", True) and e_budget > 0:
        mult = 1.0 + q_energy / (rcfg["eq_kappa"] * e_budget)
        eps[VW_CH] = np.minimum(eps[VW_CH] * mult, rcfg["eps_vw_cap"])
        eps[T_CH] = np.minimum(eps[T_CH] * mult, rcfg["eps_t_cap"])
    return eps


def must_send(x: np.ndarray, ref: np.ndarray, eps: np.ndarray) -> bool:
    """Send-on-delta test: any channel left its tolerance band, or a channel changed
    availability (became valid / invalid)."""
    vx, vr = np.isfinite(x), np.isfinite(ref)
    if np.any(vx != vr):
        return True
    m = vx & vr
    return bool(np.any(np.abs(x[m] - ref[m]) > eps[m]))


# ----------------------------------------------------------------- replica
class Replica:
    """Gateway view of every node: last reference vector, tolerance, timing, loss flag."""

    def __init__(self, n_nodes: int):
        self.v = np.full((n_nodes, N_CH), np.nan)
        self.eps = np.zeros((n_nodes, N_CH))
        self.t_rx = np.full(n_nodes, -np.inf)
        self.seq = np.full(n_nodes, -1, dtype=np.int64)
        self.lossy_until = np.full(n_nodes, -np.inf)
        self.hb = np.full(n_nodes, np.inf)   # heartbeat bound announced in the last packet
        self.t_next = np.full(n_nodes, -np.inf)  # node's next sampling instant after the
        # reported sample: until then the reported value IS the latest observation

    def update(self, n: int, seq: int, values: np.ndarray, eps: np.ndarray, t: float,
               loss_memory: float) -> bool:
        """Apply a received packet.  Returns False for duplicates/out-of-order."""
        if seq <= self.seq[n]:
            return False
        if self.seq[n] >= 0 and seq > self.seq[n] + 1:
            self.lossy_until[n] = t + loss_memory  # a gap in sequence numbers = losses
        self.seq[n] = seq
        self.v[n] = values
        self.eps[n] = eps
        self.t_rx[n] = t
        return True


def classify_member(policy: dict, rep: Replica, j: int, th: float, ev: str, t: float,
                    hb_s: float, periodic_s: float) -> str:
    """'yes' / 'no' / 'unc' (uncertain) / 'nodata' for member j w.r.t. the zone
    condition (dry: VW30 < theta; wet: VW30 > theta)."""
    v = rep.v[j, VW30]
    if not np.isfinite(v):
        return "nodata"
    e = rep.eps[j, VW30]
    validity = policy.get("validity", "heartbeat")
    if policy["retrieval"] == "periodic":
        stale = (t - rep.t_rx[j]) > periodic_s * 1.5
        e = 0.0
    else:
        hb_j = rep.hb[j] if np.isfinite(rep.hb[j]) else hb_s
        stale = (t - rep.t_rx[j]) > hb_j * 1.02 + 60.0
    if stale:
        return "unc"
    if validity == "loss_aware" and rep.lossy_until[j] > t:
        return "unc"
    if t < rep.t_next[j]:
        e = 0.0  # no newer sample exists yet: the value is exact
    lo, hi = v - e, v + e
    if ev == "dry":
        return "yes" if hi < th else ("no" if lo >= th else "unc")
    return "yes" if lo > th else ("no" if hi <= th else "unc")


def zone_status(labels: list, frac: float):
    """Interval decision for 'at least frac of the zone satisfies the condition'."""
    n = sum(1 for s in labels if s != "nodata")
    if n == 0:
        return "nodata", 0
    need = frac * n
    yes = sum(1 for s in labels if s == "yes")
    unc = sum(1 for s in labels if s == "unc")
    if yes >= need:
        return "pos", n
    if yes + unc < need:
        return "neg", n
    return "inc", n


def point_decision(rep: Replica, members: list, th: np.ndarray, ev: str, frac: float):
    """Decision from point estimates (last reference values)."""
    vals = [(rep.v[j, VW30], th[k]) for k, j in enumerate(members)]
    vals = [(v, t) for v, t in vals if np.isfinite(v)]
    if not vals:
        return None
    yes = sum(1 for v, t in vals if (v < t if ev == "dry" else v > t))
    return yes >= frac * len(vals)
