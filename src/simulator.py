"""Discrete-event simulator of the multi-layer agricultural sensing system.

Layers: sensor nodes (CAF replay) and weather stations (USCRN replay) -> LoRa
channel/gateway -> gateway controller + edge compute -> fog -> cloud (Azure-shaped
background load).  Every policy (baselines, BRISK, ablations) runs on the same
scenario generator with the same random seed, so that per-seed comparisons are paired.
"""
from __future__ import annotations

import heapq
import itertools
import math
import time
from collections import defaultdict

import numpy as np

from . import data_loading as DL
from .metrics import RunMetrics
from .network_model import Backhaul, Gateway, GELink, LocalLink, Tx, lora_toa, symbol_time
from .resource_scheduler import AzureBackground, Tier, place_task
from .retrieval import (N_CH, Replica, classify_member, must_send, point_decision,
                        range_filter, tolerance, zone_status)
from .task_model import STRATEGIC, URGENT, Task

VW30 = DL.VW30


class Bundle:
    """Datasets loaded once and shared by many runs."""

    def __init__(self, cfg: dict):
        p = cfg["data"]["processed_dir"]
        self.field = DL.load_field(p, cfg)
        self.weather = DL.load_weather(p)
        self.links = DL.load_links(p)
        import json, os
        with open(os.path.join(p, "uwa_diversity_params.json")) as f:
            self.div = {int(k): v for k, v in json.load(f).items()}
        self.azure = DL.load_azure(p)


class Simulation:
    def __init__(self, cfg: dict, policy: dict, seed: int, bundle: Bundle, name: str = ""):
        self.cfg, self.pol, self.seed, self.name = cfg, policy, seed, name
        self.B = bundle
        self.rng = np.random.default_rng(seed)
        self.H = cfg["horizon_hours"] * 3600.0
        self.ev: list = []
        self._seq = itertools.count()
        self.M = RunMetrics()
        self._build()

    # ------------------------------------------------------------ event core
    def schedule(self, t: float, kind: str, data) -> None:
        heapq.heappush(self.ev, (t, next(self._seq), kind, data))

    def run(self) -> RunMetrics:
        wall = time.perf_counter()
        handlers = {
            "sample": self._on_sample, "uplink_end": self._on_uplink_end,
            "retx": self._on_retx, "task_done": self._on_task_done,
            "task_arrive": self._on_task_arrive, "wsample": self._on_wsample,
            "map": self._on_map, "pull_slot": self._on_pull_slot,
            "guard": self._on_guard, "zone_tick": self._on_zone_tick,
            "deliver": self._on_deliver, "cmd_slot": self._on_cmd_slot,
        }
        while self.ev:
            t, _, kind, data = heapq.heappop(self.ev)
            if t > self.H:
                break
            self.now = t
            handlers[kind](t, data)
        self._finalize()
        self.M.meta["wall_s"] = time.perf_counter() - wall
        return self.M

    # ----------------------------------------------------------------- build
    def _build(self) -> None:
        cfg, rng, fd = self.cfg, self.rng, self.B.field
        lc = cfg["lora"]
        self.n_loc = len(fd.locations)
        self.K = cfg["tiles"]
        self.N = self.K * self.n_loc
        self.M.init(self.N)
        self.tile_start = DL.tile_start_hours(fd, cfg, self.K)
        # timing & radio
        self.toa_soil = lora_toa(lc["payload_soil_bytes"], lc["sf"], lc["bw_hz"], lc["cr"], lc["preamble"])
        self.toa_weather = lora_toa(lc["payload_weather_bytes"], lc["sf"], lc["bw_hz"], lc["cr"], lc["preamble"])
        self.toa_ack1 = lora_toa(lc["payload_ack_bytes"], lc["sf"], lc["bw_hz"], lc["cr"], lc["preamble"])
        self.toa_ack2 = lora_toa(lc["payload_ack_bytes"], lc["rx2_sf"], lc["bw_hz"], lc["cr"], lc["preamble"])
        self.toa_cmd1 = lora_toa(lc["payload_cmd_bytes"], lc["sf"], lc["bw_hz"], lc["cr"], lc["preamble"])
        self.toa_pull = lora_toa(lc["payload_pull_bytes"], lc["sf"], lc["bw_hz"], lc["cr"], lc["preamble"])
        self.toa_beacon = lora_toa(lc["beacon_payload_bytes"], lc["sf"], lc["bw_hz"], lc["cr"],
                                   lc["beacon_preamble"], crc=False, implicit_header=True)
        self.p_tx = lc["tx_current_a"] * lc["voltage_v"]
        self.p_rx = lc["rx_current_a"] * lc["voltage_v"]
        self.rxwin1 = lc["rx_window_symbols"] * symbol_time(lc["sf"], lc["bw_hz"])
        self.rxwin2 = lc["rx_window_symbols"] * symbol_time(lc["rx2_sf"], lc["bw_hz"])
        # Class B listening power (beacon + one empty ping slot per period)
        self.p_classb = self.p_rx * (self.toa_beacon / lc["beacon_period_s"] + self.rxwin1 / lc["class_b_period_s"])
        self.G = int(cfg.get("gateways", 1))
        self.gws = [Gateway(lc["channels"], lc["duty_rx1"], lc["duty_rx2"]) for _ in range(self.G)]
        self.gw = self.gws[0]
        # nodes
        N = self.N
        self.tile = np.repeat(np.arange(self.K), self.n_loc)
        self.loc = np.tile(np.arange(self.n_loc), self.K)
        self.zone = self.tile * cfg["zones_per_tile"] + fd.zones[self.loc]
        self.members = defaultdict(list)
        for n in range(N):
            self.members[self.zone[n]].append(n)
        self.th_dry = fd.theta_dry[self.loc]
        self.th_wet = fd.theta_wet[self.loc]
        self.phase = rng.uniform(0, cfg["sensing"]["period_s"], N)
        stations = sorted(self.B.div)
        self.link_station = rng.choice(stations, N)
        self.link = [self._make_link(int(self.link_station[n])) for n in range(N)]
        self.ref = np.full((N, N_CH), np.nan)
        self.eps_sent = np.zeros((N, N_CH))
        self.last_tx = np.full(N, -np.inf)
        self.seqno = np.zeros(N, dtype=np.int64)
        self.armed_dry = np.ones(N, bool)
        self.armed_wet = np.ones(N, bool)
        self.last_hour = np.full(N, -1, dtype=np.int64)    # cube hour of latest sample
        self.cur_x = np.full((N, N_CH), np.nan)
        self.classb = np.zeros(N, bool)
        self.classb_since = np.zeros(N)
        self.watch_node = np.zeros(N, bool)
        self.q_energy = np.zeros(N)
        self.e_hour = np.zeros(N)
        self.ping_off = rng.uniform(0, lc["class_b_period_s"], N)
        self.pending_cmd = {}   # node -> bool (desired class-B/watch state)
        self.cmd_scheduled = set()
        self.w_outstanding = {}
        self.outstanding = {}   # node -> confirmed message state
        if self.pol["class_b"] == "all":
            self.classb[:] = True
        # energy budget per node per hour (fraction of periodic reporting energy)
        e_periodic = self.toa_soil * self.p_tx + (self.rxwin1 + self.rxwin2) * self.p_rx
        self.e_budget = cfg["retrieval"]["energy_budget_frac"] * e_periodic
        # gateway side
        self.rep = Replica(N)
        self.zone_watch_until = defaultdict(lambda: -np.inf)
        self.pull_wait = defaultdict(list)  # node -> [job]
        # compute tiers
        az_off = int(rng.integers(len(self.B.azure)))
        bg = AzureBackground(self.B.azure, cfg["cloud"]["bg_rho_mean"], cfg["cloud"]["bg_rho_max"], az_off)
        disc = self.pol["discipline"]
        self.tiers = {
            "edge": Tier("edge", cfg["edge"]["cores"], cfg["edge"]["speed"], disc),
            "fog": Tier("fog", cfg["fog"]["cores"], cfg["fog"]["speed"], disc) if cfg["fog"]["enabled"] else None,
            "cloud": Tier("cloud", cfg["cloud"]["cores"], cfg["cloud"]["speed"], disc, bg=bg),
        }
        for tr in self.tiers.values():
            if tr is not None:
                tr.engine = self
        self.backhaul = Backhaul(cfg["backhaul"], np.random.default_rng(rng.integers(1 << 62)), self.H)
        self.fognet = LocalLink(cfg["fog"]["rate_bps"], cfg["fog"]["rtt_s"])
        self.links_for = {"edge": None, "fog": self.fognet, "cloud": self.backhaul}
        # weather stations: one per tile
        wd = self.B.weather
        self.w_station = [k % len(wd.names) for k in range(self.K)]
        self.w_phase = rng.uniform(0, cfg["sensing"]["weather_period_s"], self.K)
        self.w_link = [self._make_link(2) for _ in range(self.K)]
        self.w_armed_frost = np.ones(self.K, bool)
        self.w_armed_rain = np.ones(self.K, bool)
        self.w_dry_count = np.zeros(self.K, int)
        self.w_seq = np.zeros(self.K, np.int64)
        self.w_last_seq = np.full(self.K, -1, np.int64)
        import pandas as pd
        self.w_start = []
        for k in range(self.K):
            ts = fd.t0 + pd.Timedelta(hours=self.tile_start[k])
            day = pd.Timestamp(f"2023-{ts.month:02d}-{ts.day:02d}")
            self.w_start.append(int((day - wd.t0) / pd.Timedelta(minutes=5)) + 1)
        # initial events
        for n in range(N):
            self.schedule(self.phase[n], "sample", n)
        for k in range(self.K):
            self.schedule(self.w_phase[k], "wsample", k)
            self.schedule(1800.0, "map", k)
        if self.pol["class_b"] == "watch":
            self.schedule(600.0, "zone_tick", None)
        self.now = 0.0

    # ------------------------------------------------------------ helpers
    def _make_link(self, st: int):
        """Node-side chain + one receiver-specific chain per gateway (gateway 0 uses
        the UWA logger receiver's statistics, gateway 1 the second receiver's)."""
        d = self.B.div[st]
        iv = d["interval_s"] * self.cfg.get("burst_time_scale", 1.0)
        mk = lambda pp: GELink(pp["p_good_to_bad"], pp["p_bad_to_good"], iv,
                               np.random.default_rng(self.rng.integers(1 << 62)),
                               iid=self.cfg.get("link_model", "ctmc") == "iid")
        return {"node": mk(d["node_side"]), "rx": [mk(d["rx1"] if g == 0 else d["rx2"]) for g in range(self.G)]}

    def _rx_ok(self, link, g: int, t: float, node_bad: bool) -> bool:
        return (not node_bad) and (not link["rx"][g].is_bad(t))

    def _hour_index(self, n: int, t: float) -> int:
        h = int((t - self.phase[n]) // 3600.0 + 1e-9)
        return self.tile_start[self.tile[n]] + h

    def _energy_classb(self, n: int, t: float) -> None:
        if self.classb[n]:
            e = (t - self.classb_since[n]) * self.p_classb
            self.M.e_classb[n] += e
            self.e_hour[n] += e
            self.classb_since[n] = t

    def _set_classb(self, n: int, on: bool, t: float) -> None:
        if self.classb[n] == on:
            return
        self._energy_classb(n, t)
        self.classb[n] = on
        self.classb_since[n] = t
        if on:
            self.M.classb_switches += 1

    # --------------------------------------------------------- node sampling
    def _on_sample(self, t: float, n: int) -> None:
        cfg, pol = self.cfg, self.pol
        self.schedule(t + cfg["sensing"]["period_s"], "sample", n)
        h = self._hour_index(n, t)
        if h >= self.B.field.raw.shape[1]:
            return
        self.last_hour[n] = h
        x = range_filter(self.B.field.raw[self.loc[n], h, :])
        self.cur_x[n] = x
        # energy-queue update (once per sampling period, node-local)
        self._energy_classb(n, t)
        if pol.get("energy_queue") and pol["retrieval"] == "brisk":
            self.q_energy[n] = max(0.0, self.q_energy[n] + self.e_hour[n] - self.e_budget)
        self.e_hour[n] = 0.0
        if not np.isfinite(x).any():
            return
        # node-local urgent detection (identical for all policies)
        x30 = x[VW30]
        hy = cfg["events"]["hysteresis"]
        alarm = None
        if np.isfinite(x30):
            if self.armed_dry[n] and x30 < self.th_dry[n] - hy:
                alarm, self.armed_dry[n] = "dry", False
            elif not self.armed_dry[n] and x30 > self.th_dry[n] + hy:
                self.armed_dry[n] = True
            if alarm is None and self.armed_wet[n] and x30 > self.th_wet[n] + hy:
                alarm, self.armed_wet[n] = "wet", False
            elif not self.armed_wet[n] and x30 < self.th_wet[n] - hy:
                self.armed_wet[n] = True
        # retrieval decision
        if pol["retrieval"] == "periodic":
            send = True
            eps = np.zeros(N_CH)
        else:
            eps = tolerance(pol, cfg["retrieval"], x30, self.th_dry[n], self.th_wet[n],
                            bool(self.watch_node[n]), self.q_energy[n], self.e_budget)
            hb_n = self._heartbeat(n, x30)
            hb = (t - self.last_tx[n]) >= hb_n - 1.0
            send = alarm is not None or hb or must_send(x, self.ref[n], self.eps_sent[n])
        if alarm is not None:
            self.M.alarms[alarm] += 1
        if not send:
            self.M.suppressed += 1
            return
        self.seqno[n] += 1
        self.ref[n] = x
        self.eps_sent[n] = eps
        self.last_tx[n] = t
        payload = {"seq": int(self.seqno[n]), "x": x, "eps": eps, "alarm": alarm,
                   "t_sample": t, "hour": h,
                   "hb": cfg["sensing"]["period_s"] if pol["retrieval"] == "periodic" else hb_n}
        if alarm is not None:
            payload["deadline_abs"] = t + (cfg["events"]["deadline_dry_s"] if alarm == "dry"
                                           else cfg["events"]["deadline_wet_s"])
        if alarm is not None:
            self.outstanding[n] = {"payload": payload, "attempt": 0}
        self._uplink(n, t, payload, confirmed=alarm is not None, attempt=0)

    def _heartbeat(self, n: int, x30: float) -> float:
        """Fixed heartbeat H_hb, or (BRISK) urgency-proximity heartbeat
        H_i = H_min + (H_max - H_min) * clip((d_i - r0)/r, 0, 1), d_i = distance of VW30
        to the nearest decision threshold."""
        sc = self.cfg["sensing"]
        if self.pol.get("heartbeat", "fixed") == "fixed" or not np.isfinite(x30):
            return self.pol.get("hb_s", sc["heartbeat_s"])
        rc = self.cfg["retrieval"]
        d = min(abs(x30 - self.th_dry[n]), abs(x30 - self.th_wet[n]))
        frac = min(max((d - rc["prox_r0"]) / rc["prox_r"], 0.0), 1.0)
        hb = sc["hb_min_s"] + (sc["hb_max_s"] - sc["hb_min_s"]) * frac
        if self.pol.get("energy_queue") and self.e_budget > 0:
            hb = min(hb * (1.0 + self.q_energy[n] / (rc["eq_kappa"] * self.e_budget)), 2 * sc["hb_max_s"])
        return hb

    def _uplink(self, n: int, t: float, payload: dict, confirmed: bool, attempt: int,
                weather: int = -1) -> None:
        toa = self.toa_weather if weather >= 0 else self.toa_soil
        ch = int(self.rng.integers(self.cfg["lora"]["channels"]))
        tx = Tx(n if weather < 0 else -1 - weather, t, t + toa, ch, "conf" if confirmed else "unconf",
                payload, attempt=attempt)
        self.gw.start_uplink(tx)
        if weather < 0:
            e = toa * self.p_tx
            self.M.e_tx[n] += e
            self.e_hour[n] += e
            self.M.packets[n] += 1
            if attempt > 0:
                self.M.retx += 1
        self.M.uplinks += 1
        self.schedule(t + toa, "uplink_end", tx)

    def _on_uplink_end(self, t: float, tx: Tx) -> None:
        weather = tx.node < 0
        k = -1 - tx.node if weather else -1
        n = tx.node
        link = self.w_link[k] if weather else self.link[n]
        node_bad = link["node"].is_bad(tx.start)
        heard = []
        for g, gw in enumerate(self.gws):
            if tx.collided:
                gw.stats["collisions"] += 1
                continue
            if gw.blocked_by_downlink(tx.start, tx.end):
                gw.stats["half_duplex_losses"] += 1
                continue
            if self._rx_ok(link, g, tx.start, node_bad):
                heard.append(g)
        ok = bool(heard)
        if ok:
            self.M.delivered += 1
        elif not tx.collided:
            self.M.channel_losses += 1
        # ---- downlink opportunity (ACK and/or pending command) in RX1 / RX2 via a
        # gateway that heard the uplink (network-server gateway selection)
        need_ack = tx.kind == "conf" and ok
        cmd = None if weather else self.pending_cmd.get(n)
        dl_ok = False
        rx_e = (self.rxwin1 + self.rxwin2) * self.p_rx
        if ok and (need_ack or cmd is not None):
            t1, t2 = t + 1.0, t + 2.0
            toa1 = self.toa_ack1 if cmd is None else self.toa_cmd1
            sent = False
            for g in heard:
                if self.gws[g].try_downlink(t1, toa1, "rx1"):
                    dl_ok = self._rx_ok(link, g, t1, link["node"].is_bad(t1))
                    rx_e = toa1 * self.p_rx
                    sent = True
                    break
            if not sent and need_ack:
                cmd = None
                for g in heard:
                    if self.gws[g].try_downlink(t2, self.toa_ack2, "rx2"):
                        dl_ok = self._rx_ok(link, g, t2, link["node"].is_bad(t2))
                        rx_e = (self.rxwin1 + self.toa_ack2) * self.p_rx
                        sent = True
                        break
            if dl_ok and cmd is not None:
                del self.pending_cmd[n]
                self._apply_cmd(n, cmd, t1)
        if not weather:
            self.M.e_rx[n] += rx_e
            self.e_hour[n] += rx_e
        # ---- gateway receives
        if ok:
            if weather:
                self._gw_receive_weather(k, tx.payload, t)
            else:
                self._gw_receive(n, tx.payload, t, pull=tx.kind == "pull")
        # ---- confirmed-message bookkeeping on the node
        if tx.kind == "conf":
            st = self.w_outstanding.get(k) if weather else self.outstanding.get(n)
            if st is None:
                return
            if need_ack and dl_ok:
                (self.w_outstanding if weather else self.outstanding).pop(k if weather else n)
                return
            delay = self._retry_delay(st, t)
            if delay is None:
                self.M.alarm_giveups += 1
                (self.w_outstanding if weather else self.outstanding).pop(k if weather else n)
                return
            st["attempt"] += 1
            self.schedule(t + delay, "retx", (tx.node, st["attempt"]))

    def _retry_delay(self, st: dict, t: float):
        """LoRaWAN default: up to max_retx retries after RX2 + ACK_TIMEOUT (1-3 s).
        'deadline_spread' (BRISK): retries spaced geometrically so that they span the
        alarm's deadline (time diversity against bursty losses); attempts stop when the
        remaining slack cannot cover one more air time + processing."""
        lc = self.cfg["lora"]
        lo, hi = lc["ack_timeout_s"]
        if self.pol.get("retry", "standard") == "standard":
            if st["attempt"] >= lc["max_retx"]:
                return None
            return 2.0 + self.rng.uniform(lo, hi)
        dl = st["payload"].get("deadline_abs", t + 60.0)
        R = lc.get("max_retx_spread", 6)
        if st["attempt"] >= R:
            return None
        slack = dl - t - 1.0
        base = 2.0 + self.rng.uniform(lo, hi)
        # geometric spacing: next wait = max(base, slack / 2)  (halving the slack)
        wait = max(base, slack / 2.0)
        if t + wait + self.toa_soil + 0.5 > dl:
            if t + base + self.toa_soil + 0.5 > dl:
                return None
            wait = base
        return wait

    def _on_retx(self, t: float, data) -> None:
        node, attempt = data
        if node < 0:
            k = -1 - node
            st = self.w_outstanding.get(k)
            if st is None or st["attempt"] != attempt:
                return
            self._uplink(-1, t, st["payload"], True, attempt, weather=k)
        else:
            st = self.outstanding.get(node)
            if st is None or st["attempt"] != attempt:
                return
            self._uplink(node, t, st["payload"], True, attempt)

    def _apply_cmd(self, n: int, cmd: bool, t: float) -> None:
        self.watch_node[n] = cmd
        if self.pol["class_b"] == "watch":
            self._set_classb(n, cmd, t)
        self.M.commands += 1

    # ------------------------------------------------------- gateway: soil
    def _gw_receive(self, n: int, p: dict, t: float, pull: bool = False) -> None:
        cfg = self.cfg
        if not pull:
            fresh = self.rep.update(n, p["seq"], p["x"], p["eps"], t, cfg["sensing"]["loss_memory_s"])
            if not fresh:
                self.M.duplicates += 1
                return
            self.rep.t_next[n] = p["t_sample"] + cfg["sensing"]["period_s"]
            self.rep.hb[n] = p.get("hb", cfg["sensing"]["heartbeat_s"])
        else:
            # pull responses carry the node's current reference (no new sequence number)
            self.rep.v[n] = p["x"]
            self.rep.eps[n] = p["eps"]
            self.rep.t_rx[n] = t
            self.rep.t_next[n] = p["t_sample"] + cfg["sensing"]["period_s"]
        self.backhaul.send(t, cfg["tasks"]["archive_record_bytes"])
        if self.pol["class_b"] == "watch":
            self._update_watch(n, t)
        if p.get("alarm"):
            self._new_decision(n, p, t)
        if n in self.pull_wait:
            jobs = self.pull_wait.pop(n)
            for job in jobs:
                job["pending"].discard(n)
                if not job["pending"] and not job["done"]:
                    self._finish_decision(job, t)

    def _update_watch(self, n: int, t: float) -> None:
        """Zone enters watch when >= watch_frac of its members are within watch_band of
        a decision threshold (evaluated on the replica), or when an alarm occurs."""
        rc = self.cfg["retrieval"]
        z = self.zone[n]
        mem = self.members[z]
        v = self.rep.v[mem, VW30]
        ok = np.isfinite(v)
        if not ok.any():
            return
        near = ok & ((v < self.th_dry[mem] + rc["watch_band"]) | (v > self.th_wet[mem] - rc["watch_band"]))
        if near.sum() >= rc["watch_frac"] * ok.sum():
            self.zone_watch_until[z] = max(self.zone_watch_until[z], t + rc["watch_hold_s"])
        self._zone_commands(z, t)

    def _zone_commands(self, z: int, t: float) -> None:
        on = self.zone_watch_until[z] > t
        for m in self.members[z]:
            if self.watch_node[m] != on:
                self.pending_cmd[m] = on
            elif m in self.pending_cmd:
                del self.pending_cmd[m]
            if self.classb[m] and m in self.pending_cmd and m not in self.cmd_scheduled:
                # nodes already in Class B can be commanded at their next ping slot
                self.cmd_scheduled.add(m)
                self.schedule(self._next_ping(m, t + 0.05), "cmd_slot", m)

    def _on_cmd_slot(self, t: float, m: int) -> None:
        self.cmd_scheduled.discard(m)
        if m not in self.pending_cmd or not self.classb[m]:
            return
        if self.gw.try_downlink(t, self.toa_cmd1, "rx2"):
            e = self.toa_cmd1 * self.p_rx
            self.M.e_rx[m] += e
            self.e_hour[m] += e
            if self._rx_ok(self.link[m], 0, t, self.link[m]["node"].is_bad(t)):
                self._apply_cmd(m, self.pending_cmd.pop(m), t)
                return
        self.cmd_scheduled.add(m)
        self.schedule(self._next_ping(m, t + 0.05), "cmd_slot", m)

    def _on_zone_tick(self, t: float, _) -> None:
        self.schedule(t + 600.0, "zone_tick", None)
        for z in list(self.members):
            if self.zone_watch_until[z] > -np.inf:
                self._zone_commands(z, t)

    # --------------------------------------------------- decision process
    def _new_decision(self, n: int, p: dict, t: float) -> None:
        cfg, pol = self.cfg, self.pol
        ev = p["alarm"]
        z = self.zone[n]
        D = cfg["events"]["deadline_dry_s"] if ev == "dry" else cfg["events"]["deadline_wet_s"]
        job = {"node": n, "zone": z, "ev": ev, "origin": p["t_sample"], "deadline": p["t_sample"] + D,
               "t_rx": t, "pending": set(), "done": False, "pulls": 0, "forced": False,
               "hour": p["hour"], "status0": None}
        self.M.decisions_started += 1
        w0 = time.perf_counter()
        if pol["class_b"] == "watch":
            self.zone_watch_until[z] = max(self.zone_watch_until[z], t + cfg["retrieval"]["watch_hold_s"])
            self._zone_commands(z, t)
        if pol["verify"] == "point":
            self._finish_decision(job, t)
            return
        mem = self.members[z]
        th = self.th_dry[mem] if ev == "dry" else self.th_wet[mem]
        labels = [classify_member(pol, self.rep, j, th[i], ev, t, cfg["sensing"]["heartbeat_s"],
                                  cfg["sensing"]["period_s"]) for i, j in enumerate(mem)]
        status, _ = zone_status(labels, cfg["events"]["zone_fraction"])
        job["status0"] = status
        self.M.verify_wall += time.perf_counter() - w0
        self.M.verify_calls += 1
        if status != "inc":
            self._finish_decision(job, t)
            return
        if pol["verify"] == "interval_point":
            self._finish_decision(job, t, forced=True)
            return
        unc = [j for j, s in zip(mem, labels) if s == "unc" and j != n]
        pullable = [j for j in unc if self.classb[j]]
        # estimated processing+return time of the verification task (for the guard)
        guard = job["deadline"] - self._est_task_latency(t) - 0.5
        if pol.get("pull_select") == "reliable":
            pullable.sort(key=lambda j: -self.link[j]["node"].stationary_pdr() if self.rep.lossy_until[j] <= t else 0)
        P = cfg["lora"]["class_b_period_s"]
        issued = []
        for j in pullable:
            slot = self._next_ping(j, t + 0.05)
            if slot + self.toa_pull + self.toa_soil + 0.2 <= guard:
                issued.append((j, slot))
        if not issued:
            self._finish_decision(job, t, forced=True)
            return
        for j, slot in issued:
            job["pending"].add(j)
            self.pull_wait[j].append(job)
            self.schedule(slot, "pull_slot", (j, job))
            job["pulls"] += 1
        self.schedule(max(guard, t), "guard", job)

    def _next_ping(self, j: int, t: float) -> float:
        P = self.cfg["lora"]["class_b_period_s"]
        k = math.ceil((t - self.ping_off[j]) / P)
        return self.ping_off[j] + k * P

    def _on_pull_slot(self, t: float, data) -> None:
        j, job = data
        if job["done"]:
            return
        self.M.pulls += 1
        if not self.classb[j]:
            return
        if not self.gw.try_downlink(t, self.toa_pull, "rx2"):
            self._retry_pull(j, job, t)
            return
        e = self.toa_pull * self.p_rx
        self.M.e_rx[j] += e
        self.e_hour[j] += e
        if not self._rx_ok(self.link[j], 0, t, self.link[j]["node"].is_bad(t)):
            self._retry_pull(j, job, t)
            return
        # node answers with its current reference values
        x = self.cur_x[j]
        self.ref[j] = x
        last_sample = self.phase[j] + ((t - self.phase[j]) // 3600.0) * 3600.0
        payload = {"seq": -1, "x": x, "eps": self.eps_sent[j].copy(), "alarm": None,
                   "t_sample": last_sample, "hour": self.last_hour[j]}
        toa = self.toa_soil
        ch = int(self.rng.integers(self.cfg["lora"]["channels"]))
        t0 = t + self.toa_pull + 0.1
        tx = Tx(j, t0, t0 + toa, ch, "pull", payload)
        self.gw.start_uplink(tx)
        e = toa * self.p_tx
        self.M.e_tx[j] += e
        self.e_hour[j] += e
        self.M.packets[j] += 1
        self.M.uplinks += 1
        self.schedule(t0 + toa, "uplink_end", tx)

    def _retry_pull(self, j: int, job: dict, t: float) -> None:
        slot = self._next_ping(j, t + 0.05)
        guard = job["deadline"] - self._est_task_latency(t) - 0.5
        if slot + self.toa_pull + self.toa_soil + 0.2 <= guard:
            self.schedule(slot, "pull_slot", (j, job))

    def _on_guard(self, t: float, job: dict) -> None:
        if not job["done"]:
            self._finish_decision(job, t, forced=bool(job["pending"]))

    def _est_task_latency(self, t: float) -> float:
        task = Task("verify", t, t + 1e9, self.cfg["tasks"]["verify_work_s"], self.cfg["tasks"]["verify_in_bytes"],
                    self.cfg["tasks"]["verify_out_bytes"], URGENT)
        tier = place_task(self.pol, task, t, self.tiers, self.links_for)
        lk = self.links_for[tier]
        up = lk.estimate(t, task.b_in) if lk else 0.0
        down = lk.estimate(t, task.b_out) if lk else 0.0
        return self.tiers[tier].estimate_finish(t + up, task) + down - t

    def _finish_decision(self, job: dict, t: float, forced: bool = False) -> None:
        job["done"] = True
        for j in list(job["pending"]):
            if j in self.pull_wait and job in self.pull_wait[j]:
                self.pull_wait[j].remove(job)
        job["forced"] = forced
        cfg, pol = self.cfg, self.pol
        mem = self.members[job["zone"]]
        ev = job["ev"]
        th = self.th_dry[mem] if ev == "dry" else self.th_wet[mem]
        frac = cfg["events"]["zone_fraction"]
        if pol["verify"] == "point":
            dec = point_decision(self.rep, mem, th, ev, frac)
        else:
            labels = [classify_member(pol, self.rep, j, th[i], ev, t, cfg["sensing"]["heartbeat_s"],
                                      cfg["sensing"]["period_s"]) for i, j in enumerate(mem)]
            status, _ = zone_status(labels, frac)
            dec = (status == "pos") if status in ("pos", "neg") else point_decision(self.rep, mem, th, ev, frac)
            if status == "inc":
                job["forced"] = True
        job["decision"] = dec
        job["truth"], job["truth_margin"] = self._truth(job, mem, th)
        task = Task("verify", t, job["deadline"], cfg["tasks"]["verify_work_s"], cfg["tasks"]["verify_in_bytes"],
                    cfg["tasks"]["verify_out_bytes"], URGENT, origin=job["origin"], meta={"job": job})
        self._dispatch(task, t)

    def _truth(self, job: dict, mem: list, th: np.ndarray):
        """Zone condition evaluated on the QC'd reference values of the members'
        latest samples taken at or before the alarm sample (perfect-retrieval answer)."""
        qc = self.B.field.qc
        t_al = job["origin"]
        yes = tot = 0
        for i, j in enumerate(mem):
            h = self._hour_index(j, t_al)
            v = qc[self.loc[j], h, VW30]
            if not np.isfinite(v):
                continue
            tot += 1
            yes += (v < th[i]) if job["ev"] == "dry" else (v > th[i])
        if tot < 3:
            return None, np.nan
        f = self.cfg["events"]["zone_fraction"]
        return bool(yes >= f * tot), yes / tot - f

    # --------------------------------------------------------- weather
    def _on_wsample(self, t: float, k: int) -> None:
        cfg = self.cfg
        self.schedule(t + cfg["sensing"]["weather_period_s"], "wsample", k)
        wd = self.B.weather
        i = self.w_start[k] + int((t - self.w_phase[k]) // cfg["sensing"]["weather_period_s"])
        s = self.w_station[k]
        if i >= wd.t_air.shape[1]:
            return
        ta, pr = wd.t_air[s, i], wd.precip[s, i]
        alarm = None
        ev = cfg["events"]
        if np.isfinite(ta):
            if self.w_armed_frost[k] and ta <= ev["frost_c"]:
                alarm, self.w_armed_frost[k] = "frost", False
            elif not self.w_armed_frost[k] and ta > ev["frost_c"] + 1.0:
                self.w_armed_frost[k] = True
        if np.isfinite(pr):
            if self.w_armed_rain[k] and pr >= ev["heavy_rain_mm"] and alarm is None:
                alarm, self.w_armed_rain[k] = "rain", False
            if pr < 0.2:
                self.w_dry_count[k] += 1
                if self.w_dry_count[k] >= 6:
                    self.w_armed_rain[k] = True
            else:
                self.w_dry_count[k] = 0
        self.w_seq[k] += 1
        payload = {"seq": int(self.w_seq[k]), "alarm": alarm, "t_sample": t,
                   "deadline_abs": t + cfg["events"]["deadline_weather_s"]}
        if alarm is not None:
            self.M.alarms[alarm] += 1
            if not hasattr(self, "w_outstanding"):
                self.w_outstanding = {}
            self.w_outstanding[k] = {"payload": payload, "attempt": 0}
        self._uplink(-1, t, payload, alarm is not None, 0, weather=k)

    def _gw_receive_weather(self, k: int, p: dict, t: float) -> None:
        if p["seq"] <= self.w_last_seq[k]:
            return
        self.w_last_seq[k] = p["seq"]
        self.backhaul.send(t, self.cfg["tasks"]["archive_record_bytes"])
        if p["alarm"]:
            c = self.cfg
            task = Task("weather", t, p["t_sample"] + c["events"]["deadline_weather_s"], c["tasks"]["weather_work_s"],
                        c["tasks"]["weather_in_bytes"], c["tasks"]["verify_out_bytes"], URGENT,
                        origin=p["t_sample"], meta={"ev": p["alarm"]})
            self._dispatch(task, t)

    # ----------------------------------------------------------- strategic
    def _on_map(self, t: float, k: int) -> None:
        self.schedule(t + 3600.0, "map", k)
        c = self.cfg
        # fidelity of the gateway replica vs ground truth at map time (VW channels)
        nodes = np.where(self.tile == k)[0]
        qc = self.B.field.qc
        err, cov_have, cov_need = [], 0, 0
        for n in nodes:
            if self.last_hour[n] < 0:
                continue
            truth = qc[self.loc[n], self.last_hour[n], 0:5]
            est = self.rep.v[n, 0:5]
            m = np.isfinite(truth)
            cov_need += int(m.sum())
            mm = m & np.isfinite(est)
            cov_have += int(mm.sum())
            if mm.any():
                err.append(est[mm] - truth[mm])
        if err:
            e = np.concatenate(err)
            self.M.map_sq_err += float((e ** 2).sum())
            self.M.map_n += len(e)
            self.M.map_abs_max = max(self.M.map_abs_max, float(np.abs(e).max()))
        self.M.map_cov_have += cov_have
        self.M.map_cov_need += cov_need
        self._track_zones(k, t)
        task = Task("map", t, t + c["tasks"]["map_deadline_s"], c["tasks"]["map_work_s"], 0,
                    c["tasks"]["map_out_bytes"], STRATEGIC, origin=t, meta={"tile": k})
        self._dispatch(task, t)

    def _track_zones(self, k: int, t: float) -> None:
        """Hourly zone-state tracking: the decision the gateway would take now for every
        zone of tile k and both events, versus the decision on QC'd reference data of
        the members' latest samples.  Pure measurement (no state change)."""
        cfg, pol = self.cfg, self.pol
        frac = cfg["events"]["zone_fraction"]
        Z = cfg["zones_per_tile"]
        qc = self.B.field.qc
        for zz in range(Z):
            z = k * Z + zz
            mem = self.members[z]
            if any(self.last_hour[j] < 0 for j in mem):
                continue
            for ev in ("dry", "wet"):
                th = self.th_dry[mem] if ev == "dry" else self.th_wet[mem]
                yes = tot = 0
                for i, j in enumerate(mem):
                    v = qc[self.loc[j], self.last_hour[j], VW30]
                    if np.isfinite(v):
                        tot += 1
                        yes += (v < th[i]) if ev == "dry" else (v > th[i])
                if tot < 3:
                    continue
                truth = yes >= frac * tot
                margin = yes / tot - frac
                if pol["verify"] == "point":
                    dec = point_decision(self.rep, mem, th, ev, frac)
                else:
                    labels = [classify_member(pol, self.rep, j, th[i], ev, t, cfg["sensing"]["heartbeat_s"],
                                              cfg["sensing"]["period_s"]) for i, j in enumerate(mem)]
                    st, _ = zone_status(labels, frac)
                    dec = (st == "pos") if st in ("pos", "neg") else point_decision(self.rep, mem, th, ev, frac)
                if dec is None:
                    continue
                ok = int(dec == truth)
                self.M.track_n += 1
                self.M.track_ok += ok
                self.M.track_pos += int(truth)
                if abs(margin) <= 0.15:
                    self.M.track_hard_n += 1
                    self.M.track_hard_ok += ok

    # ----------------------------------------------------------- dispatch
    def _dispatch(self, task: Task, t: float) -> None:
        c = self.cfg["tasks"]
        w0 = time.perf_counter()
        if task.kind == "map":
            task.b_in = c["map_in_bytes_cloud"]
            tier = place_task(self.pol, task, t, self.tiers, self.links_for)
            task.b_in = c["map_in_bytes_cloud"] if tier == "cloud" else (c["map_in_bytes_local"] if tier == "fog" else 0)
        else:
            tier = place_task(self.pol, task, t, self.tiers, self.links_for)
        self.M.sched_wall += time.perf_counter() - w0
        self.M.sched_calls += 1
        task.tier = tier
        lk = self.links_for[tier]
        arrive = lk.send(t, task.b_in) if (lk is not None and task.b_in > 0) else t
        self.schedule(arrive, "task_arrive", task)

    def _on_task_arrive(self, t: float, task: Task) -> None:
        self.tiers[task.tier].submit(t, task)

    def _on_task_done(self, t: float, data) -> None:
        tier, task, version = data
        if not tier.complete(t, task, version):
            return
        lk = self.links_for[task.tier]
        if task.kind == "map":
            # product upload to cloud store when computed outside the cloud (no deadline)
            if task.tier != "cloud":
                self.backhaul.send(t, task.b_out)
            self._record(task, t)
            return
        arrive = lk.send(t, task.b_out) if lk is not None else t
        self.schedule(arrive, "deliver", task)

    def _on_deliver(self, t: float, task: Task) -> None:
        self._record(task, t)

    def _record(self, task: Task, t: float) -> None:
        task.t_delivered = t
        self.M.record_task(task)

    def _finalize(self) -> None:
        for n in range(self.N):
            self._energy_classb(n, self.H)
        self.M.finalize(self)
