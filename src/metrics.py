"""Per-run metric collection.  Measurement boundaries (paper Sec. 6.4):

* Urgent decision latency  = delivery of the decision at the gateway (actuation point)
  minus the sampling instant of the alarm observation.  It includes LoRa air time,
  retransmissions, ACK timeouts, context pulls, transfers, queueing, execution and the
  return path.  Deadline met <=> latency <= deadline.
* Decision accuracy         = agreement of the zone decision with the decision computed
  on QC'd reference data of the members' latest samples (perfect retrieval).
* Map RMSE                  = RMSE between the gateway replica and the QC'd reference of
  the latest samples, over VW channels, evaluated at every hourly map instant.
* Node energy               = radio energy only (TX, RX windows, Class-B beacon/ping
  listening), from SX1276 datasheet currents; sensing/MCU energy is identical across
  policies and excluded.
"""
from __future__ import annotations

from collections import Counter

import numpy as np


class RunMetrics:
    def __init__(self):
        self.meta = {}
        self.alarms = Counter()
        self.tasks = []
        self.suppressed = self.uplinks = self.delivered = self.retx = 0
        self.channel_losses = self.duplicates = self.alarm_giveups = 0
        self.pulls = self.commands = self.classb_switches = 0
        self.decisions_started = 0
        self.map_sq_err = 0.0
        self.map_n = 0
        self.map_abs_max = 0.0
        self.map_cov_have = self.map_cov_need = 0
        self.sched_wall = 0.0
        self.sched_calls = 0
        self.track_n = self.track_ok = self.track_pos = 0
        self.track_hard_n = self.track_hard_ok = 0
        self.verify_wall = 0.0
        self.verify_calls = 0

    def init(self, n: int) -> None:
        self.e_tx = np.zeros(n)
        self.e_rx = np.zeros(n)
        self.e_classb = np.zeros(n)
        self.packets = np.zeros(n, dtype=np.int64)

    def record_task(self, task) -> None:
        row = {"kind": task.kind, "tier": task.tier, "origin": task.origin, "arrival": task.arrival,
               "deadline": task.deadline, "t_start": task.t_start, "t_done": task.t_done,
               "t_delivered": task.t_delivered}
        if task.kind == "verify":
            job = task.meta["job"]
            row.update(ev=job["ev"], decision=job["decision"], truth=job["truth"],
                       forced=job["forced"], pulls=job["pulls"], status0=job["status0"],
                       truth_margin=job.get("truth_margin", np.nan),
                       zone=int(job["zone"]))
        elif task.kind == "weather":
            row.update(ev=task.meta["ev"])
        self.tasks.append(row)

    def finalize(self, sim) -> None:
        days = sim.H / 86400.0
        self.meta.update(policy=sim.name, seed=sim.seed, nodes=sim.N, tiles=sim.K, days=days,
                         gw={k: sum(g.stats[k] for g in sim.gws) for k in sim.gw.stats}, backhaul_bytes=sim.backhaul.bytes,
                         backhaul_bad_frac=sim.backhaul.bad_time(0, sim.H) / sim.H,
                         fog_bytes=sim.fognet.bytes,
                         busy={k: (v.busy_time if v is not None else 0.0) for k, v in sim.tiers.items()},
                         toa_soil=sim.toa_soil, p_classb_w=sim.p_classb)

    # ------------------------------------------------------------ summary
    def summary(self) -> dict:
        m = self.meta
        days, N = m["days"], m["nodes"]
        s = {"policy": m["policy"], "seed": m["seed"], "nodes": N, "tiles": m["tiles"]}
        e_tot = self.e_tx + self.e_rx + self.e_classb
        s["energy_J_node_day"] = float(e_tot.mean() / days)
        s["energy_tx_J_node_day"] = float(self.e_tx.mean() / days)
        s["energy_rx_J_node_day"] = float(self.e_rx.mean() / days)
        s["energy_classb_J_node_day"] = float(self.e_classb.mean() / days)
        s["energy_p95_J_node_day"] = float(np.percentile(e_tot, 95) / days)
        s["packets_node_day"] = float(self.packets.mean() / days)
        s["uplinks"] = self.uplinks
        s["pdr"] = self.delivered / max(self.uplinks, 1)
        s["collisions"] = m["gw"]["collisions"]
        s["half_duplex_losses"] = m["gw"]["half_duplex_losses"]
        s["dl_blocked_duty"] = m["gw"]["dl_blocked_duty"]
        s["retx"] = self.retx
        s["alarm_giveups"] = self.alarm_giveups
        s["pulls"] = self.pulls
        s["commands"] = self.commands
        s["alarms_dry"] = self.alarms["dry"]
        s["alarms_wet"] = self.alarms["wet"]
        s["alarms_weather"] = self.alarms["frost"] + self.alarms["rain"]
        s["track_n"] = self.track_n
        s["track_accuracy"] = self.track_ok / max(self.track_n, 1)
        s["track_error"] = 1 - s["track_accuracy"]
        s["track_hard_n"] = self.track_hard_n
        s["track_hard_accuracy"] = self.track_hard_ok / max(self.track_hard_n, 1)
        s["track_pos_frac"] = self.track_pos / max(self.track_n, 1)
        s["map_rmse"] = float(np.sqrt(self.map_sq_err / max(self.map_n, 1)))
        s["map_max_abs_err"] = self.map_abs_max
        s["map_coverage"] = self.map_cov_have / max(self.map_cov_need, 1)
        s["backhaul_MB"] = m["backhaul_bytes"] / 1e6
        s["backhaul_bad_frac"] = m["backhaul_bad_frac"]
        H = days * 86400
        s["util_edge"] = m["busy"]["edge"] / H
        s["util_fog"] = m["busy"]["fog"] / (H * 4) if m["busy"].get("fog") else 0.0
        s["util_cloud"] = m["busy"]["cloud"] / (H * 16)
        s["sched_us_per_call"] = 1e6 * self.sched_wall / max(self.sched_calls, 1)
        s["wall_s"] = m.get("wall_s", 0.0)
        # tasks
        t = self.tasks
        for kind in ("verify", "weather", "map"):
            rows = [r for r in t if r["kind"] == kind]
            lat = np.array([r["t_delivered"] - r["origin"] for r in rows]) if rows else np.array([])
            met = np.array([r["t_delivered"] <= r["deadline"] + 1e-9 for r in rows]) if rows else np.array([])
            s[f"{kind}_n"] = len(rows)
            s[f"{kind}_lat_mean"] = float(lat.mean()) if len(lat) else np.nan
            s[f"{kind}_lat_p50"] = float(np.median(lat)) if len(lat) else np.nan
            s[f"{kind}_lat_p95"] = float(np.percentile(lat, 95)) if len(lat) else np.nan
            s[f"{kind}_dsr"] = float(met.mean()) if len(met) else np.nan
            tiers = [r["tier"] for r in rows]
            for tr in ("edge", "fog", "cloud"):
                s[f"{kind}_frac_{tr}"] = (tiers.count(tr) / len(tiers)) if tiers else np.nan
        ver = [r for r in t if r["kind"] == "verify" and r["truth"] is not None and r["decision"] is not None]
        s["verify_scored"] = len(ver)
        s["verify_accuracy"] = float(np.mean([r["decision"] == r["truth"] for r in ver])) if ver else np.nan
        hard = [r for r in ver if abs(r["truth_margin"]) <= 0.15]
        s["verify_hard_n"] = len(hard)
        s["verify_hard_accuracy"] = float(np.mean([r["decision"] == r["truth"] for r in hard])) if hard else np.nan
        s["verify_us_per_call"] = 1e6 * self.verify_wall / max(self.verify_calls, 1)
        pos = [r for r in ver if r["decision"]]
        s["false_actuation_rate"] = float(np.mean([not r["truth"] for r in pos])) if pos else 0.0
        tp = [r for r in ver if r["truth"]]
        s["missed_actuation_rate"] = float(np.mean([not r["decision"] for r in tp])) if tp else 0.0
        # 'correct and on time': the decision is right AND delivered before the deadline
        s["verify_correct_on_time"] = float(np.mean([(r["decision"] == r["truth"]) and
                                                     (r["t_delivered"] <= r["deadline"] + 1e-9)
                                                     for r in ver])) if ver else np.nan
        vrows = [r for r in t if r["kind"] == "verify"]
        s["verify_forced_frac"] = float(np.mean([r["forced"] for r in vrows])) if vrows else np.nan
        s["verify_conclusive0"] = float(np.mean([r["status0"] in ("pos", "neg") for r in vrows
                                                 if r["status0"] is not None])) if any(
            r["status0"] is not None for r in vrows) else np.nan
        s["decisions_lost"] = self.decisions_started - len(vrows)
        # urgent success over *all alarms raised by nodes* (an alarm whose packet never
        # reaches the gateway counts as a deadline miss)
        raised = self.alarms["dry"] + self.alarms["wet"]
        on_time = sum(1 for r in vrows if r["t_delivered"] <= r["deadline"] + 1e-9)
        s["urgent_soil_raised"] = raised
        s["urgent_soil_success"] = on_time / raised if raised else np.nan
        ok_correct = sum(1 for r in vrows if r["t_delivered"] <= r["deadline"] + 1e-9
                         and r["truth"] is not None and r["decision"] == r["truth"])
        scored = sum(1 for r in vrows if r["truth"] is not None)
        s["urgent_soil_correct_on_time"] = ok_correct / max(scored + (raised - len(vrows)), 1)
        wr = self.alarms["frost"] + self.alarms["rain"]
        won = sum(1 for r in t if r["kind"] == "weather" and r["t_delivered"] <= r["deadline"] + 1e-9)
        s["urgent_weather_success"] = won / wr if wr else np.nan
        return s
