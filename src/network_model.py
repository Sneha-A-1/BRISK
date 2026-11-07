"""Radio, link and backhaul models.

* LoRa time-on-air follows the Semtech SX1276 datasheet (Rev. 7, 2020), Sec. 4.1.1.7.
* Packet loss on the sensor-to-gateway link is a two-state (Gilbert-Elliott) Markov
  process whose parameters are fitted per station on the UWA underground-farm LoRa
  trace (see preprocessing.preprocess_uwa).  Losses in the 'bad' state are certain;
  this is the maximum-likelihood fit of a simple Gilbert model to the observed
  sequence-number gaps.
* Collisions (same channel, time overlap) and gateway half-duplex blocking are
  simulated explicitly.  Gateway downlinks obey per-sub-band duty-cycle budgets.
* The backhaul is a FIFO link whose rate/RTT alternate between a good and a degraded
  state (exponential holding times).  Its parameters are assumptions documented in
  config/network.yaml and varied in the sensitivity study.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


# ----------------------------------------------------------------- LoRa PHY
def lora_toa(payload_bytes: int, sf: int, bw_hz: float = 125e3, cr: int = 1,
             preamble: int = 8, crc: bool = True, implicit_header: bool = False) -> float:
    """Time on air (s) of one LoRa frame (SX1276 datasheet, Sec. 4.1.1.7)."""
    ts = (2 ** sf) / bw_hz
    de = 1 if ts > 0.016 else 0  # LowDataRateOptimize mandated above 16 ms symbols
    ih = 1 if implicit_header else 0
    num = 8 * payload_bytes - 4 * sf + 28 + 16 * int(crc) - 20 * ih
    n_payload = 8 + max(math.ceil(num / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (preamble + 4.25) * ts + n_payload * ts


def symbol_time(sf: int, bw_hz: float = 125e3) -> float:
    return (2 ** sf) / bw_hz


# ------------------------------------------------------- Gilbert-Elliott link
class GELink:
    """Continuous-time two-state Markov link.  The per-packet transition
    probabilities fitted on the UWA trace (packets spaced by `interval_s`) are
    converted to rates q_gb = -ln(1-p_gb)/interval, q_bg = -ln(1-p_bg)/interval."""

    __slots__ = ("q_gb", "q_bg", "state_bad", "t_last", "rng", "iid")

    def __init__(self, p_gb: float, p_bg: float, interval_s: float, rng: np.random.Generator,
                 iid: bool = False):
        self.iid = iid
        p_gb = min(max(p_gb, 1e-6), 0.999)
        p_bg = min(max(p_bg, 1e-6), 0.999)
        self.q_gb = -math.log(1 - p_gb) / interval_s
        self.q_bg = -math.log(1 - p_bg) / interval_s
        pi_bad = self.q_gb / (self.q_gb + self.q_bg)
        self.rng = rng
        self.state_bad = bool(rng.random() < pi_bad)
        self.t_last = 0.0

    def stationary_pdr(self) -> float:
        return self.q_bg / (self.q_gb + self.q_bg)

    def is_bad(self, t: float) -> bool:
        """Sample the state at time t >= t_last (exact two-state CTMC transition)."""
        if self.iid:  # memoryless variant (sensitivity study): stationary loss, no bursts
            return bool(self.rng.random() < self.q_gb / (self.q_gb + self.q_bg))
        dt = max(t - self.t_last, 0.0)
        s = self.q_gb + self.q_bg
        pi_bad = self.q_gb / s
        e = math.exp(-s * dt)
        p_bad = pi_bad + ((1.0 if self.state_bad else 0.0) - pi_bad) * e
        self.state_bad = bool(self.rng.random() < p_bad)
        self.t_last = t
        return self.state_bad


# ------------------------------------------------------------ Gateway/channel
@dataclass
class Tx:
    node: int
    start: float
    end: float
    channel: int
    kind: str
    payload: dict
    collided: bool = False
    attempt: int = 0


@dataclass
class Gateway:
    channels: int
    duty_uplink_band: float  # duty cycle of the sub-band shared by uplink channels (RX1)
    duty_rx2_band: float     # duty cycle of the RX2 / ping-slot sub-band
    active: dict = field(default_factory=dict)  # channel -> list[Tx]
    dl_busy: list = field(default_factory=list)  # list of (start, end) downlink intervals
    next_ok_rx1: float = 0.0
    next_ok_rx2: float = 0.0
    stats: dict = field(default_factory=lambda: {"collisions": 0, "half_duplex_losses": 0,
                                                  "dl_sent": 0, "dl_blocked_duty": 0})

    def start_uplink(self, tx: Tx) -> None:
        lst = self.active.setdefault(tx.channel, [])
        lst[:] = [o for o in lst if o.end > tx.start]
        for o in lst:
            if o.end > tx.start:
                o.collided = True
                tx.collided = True
        lst.append(tx)

    def blocked_by_downlink(self, start: float, end: float) -> bool:
        self.dl_busy = [iv for iv in self.dl_busy if iv[1] > start - 300.0]
        return any(s < end and e > start for s, e in self.dl_busy)

    def try_downlink(self, t: float, toa: float, band: str) -> bool:
        """Reserve a downlink of duration `toa` at time t on the RX1 ('up') or RX2 band
        if the duty-cycle budget allows it (off-time = toa/duty - toa)."""
        if band == "rx1":
            if t < self.next_ok_rx1:
                self.stats["dl_blocked_duty"] += 1
                return False
            self.next_ok_rx1 = t + toa / self.duty_uplink_band
        else:
            if t < self.next_ok_rx2:
                self.stats["dl_blocked_duty"] += 1
                return False
            self.next_ok_rx2 = t + toa / self.duty_rx2_band
        self.dl_busy.append((t, t + toa))
        self.stats["dl_sent"] += 1
        return True


# ------------------------------------------------------------------ Backhaul
class Backhaul:
    """Gateway-to-cloud link: FIFO transmission queue, two-state rate/RTT process."""

    def __init__(self, cfg: dict, rng: np.random.Generator, horizon_s: float):
        self.good = cfg["good"]
        self.bad = cfg["bad"]
        self.busy_until = 0.0
        self.bytes = 0
        # pre-sample the state path
        t, bad = 0.0, False
        self.switch_t, self.switch_bad = [0.0], [False]
        while t < horizon_s + 3600:
            mean = cfg["mean_bad_s"] if bad else cfg["mean_good_s"]
            t += rng.exponential(mean)
            bad = not bad
            self.switch_t.append(t)
            self.switch_bad.append(bad)
        self.switch_t = np.array(self.switch_t)
        self.switch_bad = np.array(self.switch_bad)

    def state(self, t: float) -> dict:
        i = int(np.searchsorted(self.switch_t, t, side="right") - 1)
        return self.bad if self.switch_bad[i] else self.good

    def bad_time(self, t0: float, t1: float) -> float:
        """Seconds spent in the degraded state during [t0, t1] (for reporting)."""
        tot = 0.0
        for i in range(len(self.switch_t) - 1):
            a, b = max(self.switch_t[i], t0), min(self.switch_t[i + 1], t1)
            if b > a and self.switch_bad[i]:
                tot += b - a
        return tot

    def send(self, t: float, nbytes: int) -> float:
        """Enqueue nbytes at time t; return arrival time at the far end."""
        start = max(t, self.busy_until)
        st = self.state(start)
        tx = nbytes * 8.0 / st["rate_bps"]
        self.busy_until = start + tx
        self.bytes += nbytes
        return self.busy_until + st["rtt_s"] / 2.0

    def estimate(self, t: float, nbytes: int) -> float:
        """Expected one-way delivery delay for nbytes sent now (no reservation)."""
        st = self.state(t)
        return max(self.busy_until - t, 0.0) + nbytes * 8.0 / st["rate_bps"] + st["rtt_s"] / 2.0


class LocalLink:
    """Gateway-to-fog link (fixed rate/RTT, FIFO)."""

    def __init__(self, rate_bps: float, rtt_s: float):
        self.rate, self.rtt, self.busy_until, self.bytes = rate_bps, rtt_s, 0.0, 0

    def send(self, t: float, nbytes: int) -> float:
        start = max(t, self.busy_until)
        self.busy_until = start + nbytes * 8.0 / self.rate
        self.bytes += nbytes
        return self.busy_until + self.rtt / 2.0

    def estimate(self, t: float, nbytes: int) -> float:
        return max(self.busy_until - t, 0.0) + nbytes * 8.0 / self.rate + self.rtt / 2.0
