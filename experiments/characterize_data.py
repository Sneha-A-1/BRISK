"""Trace characterisation used in Sec. 6.1 of the paper (no simulation involved).

(1) UWA two-receiver loss decomposition per station -> results/tables/uwa_loss_decomposition.csv
(2) Send-on-delta transmissions vs tolerance and heartbeat on the CAF replay windows
    (6 fields x 120 days, constant predictor, loss-free)  -> results/tables/sod_offline.csv
(3) Figure: per-station delivery ratios (rx1, rx2, union, union-if-independent)

    python experiments/characterize_data.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src import data_loading as DL  # noqa: E402


def uwa_table():
    d = json.load(open(os.path.join(ROOT, "data/processed/uwa_diversity_params.json")))
    rows = []
    for st, v in d.items():
        mb = lambda p: 1.0 / max(p["p_bad_to_good"], 1e-9)  # mean burst length (packets)
        rows.append({"station": int(st), "packets": v["n"], "pdr_rx1": v["pdr_rx1"], "pdr_rx2": v["pdr_rx2"],
                     "pdr_union": v["pdr_union"], "pdr_union_if_independent": v["pdr_union_if_independent"],
                     "node_side_loss": round(1 - v["pdr_union"], 4),
                     "node_side_mean_burst_pkts": round(mb(v["node_side"]), 2),
                     "node_side_mean_burst_min": round(mb(v["node_side"]) * v["interval_s"] / 60, 1),
                     "rx1_mean_burst_pkts": round(mb(v["rx1"]), 2)})
    return pd.DataFrame(rows)


def sod_offline(cfg):
    fd = DL.load_field(os.path.join(ROOT, cfg["data"]["processed_dir"]), cfg)
    starts = DL.tile_start_hours(fd, cfg, 6)
    H = cfg["horizon_hours"]
    rows = []
    for eps in (0.002, 0.005, 0.01, 0.02):
        for hb in (2, 6, 12, 24, 10**9):
            tx = n = 0
            hb_tx = 0
            sq = cnt = 0
            for s in starts:
                x = fd.raw[:, s:s + H, :5].astype(float)
                x[(x < 0) | (x > 0.6)] = np.nan
                qc = fd.qc[:, s:s + H, :5].astype(float)
                ref = np.full((42, 5), np.nan)
                last = np.full(42, -10**9)
                for h in range(H):
                    xh = x[:, h, :]
                    have = np.isfinite(xh).any(1)
                    chg = (np.isfinite(xh) != np.isfinite(ref)).any(1) | np.nan_to_num(
                        np.abs(xh - ref) > eps, nan=False).any(1)
                    beat = (h - last) >= hb
                    send = have & (chg | beat)
                    hb_tx += int((have & beat & ~chg).sum())
                    ref[send] = xh[send]
                    last[send] = h
                    tx += int(send.sum())
                    n += int(have.sum())
                    m = np.isfinite(qc[:, h, :]) & np.isfinite(ref)
                    sq += float(((ref - qc[:, h, :])[m] ** 2).sum())
                    cnt += int(m.sum())
            rows.append({"eps": eps, "heartbeat_h": hb if hb < 10**9 else np.inf,
                         "tx_per_node_day": tx / (6 * 42 * H / 24),
                         "tx_fraction_of_samples": tx / n,
                         "heartbeat_share": hb_tx / max(tx, 1),
                         "replica_rmse": np.sqrt(sq / cnt)})
            print(rows[-1], flush=True)
    return pd.DataFrame(rows)


def main():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config/default.yaml")))
    out = os.path.join(ROOT, "results/tables")
    os.makedirs(out, exist_ok=True)
    u = uwa_table()
    u.to_csv(os.path.join(out, "uwa_loss_decomposition.csv"), index=False)
    print(u.to_string())
    s = sod_offline(cfg)
    s.to_csv(os.path.join(out, "sod_offline.csv"), index=False)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "font.family": "serif"})
    fig, ax = plt.subplots(1, 2, figsize=(6.8, 2.3))
    w = 0.2
    xs = np.arange(len(u))
    for i, (c, lab, hatch) in enumerate([("pdr_rx1", "receiver 1", ""), ("pdr_rx2", "receiver 2", "///"),
                                         ("pdr_union", "either (measured)", ".."),
                                         ("pdr_union_if_independent", "either (if independent)", "xx")]):
        ax[0].bar(xs + (i - 1.5) * w, u[c], w, label=lab, color=str(0.25 + 0.18 * i), hatch=hatch,
                  edgecolor="black", linewidth=0.4)
    ax[0].set_xticks(xs, [f"st{s}" for s in u.station])
    ax[0].set_ylim(0, 1.05)
    ax[0].set_ylabel("Packet delivery ratio")
    ax[0].legend(fontsize=6, loc="lower left", ncol=2, framealpha=0.9)
    ax[0].set_title("(a) UWA two-receiver trace", fontsize=8)
    for eps, mk in zip((0.002, 0.005, 0.02), ("o", "s", "^")):
        d = s[(s.eps == eps) & np.isfinite(s.heartbeat_h)]
        ax[1].plot(d.heartbeat_h, d.tx_per_node_day, marker=mk, color="black", lw=0.8, ms=3,
                   label=f"eps={eps}")
    ax[1].axhline(24, ls=":", color="gray", lw=0.8)
    ax[1].text(2.2, 20.5, "periodic (24/day)", fontsize=6, color="gray")
    ax[1].set_xscale("log")
    ax[1].set_xticks([2, 6, 12, 24], ["2", "6", "12", "24"])
    ax[1].set_xlabel("Heartbeat H (h)")
    ax[1].set_ylabel("Transmissions / node / day")
    ax[1].set_ylim(0, 26)
    ax[1].legend(fontsize=6)
    ax[1].set_title("(b) CAF send-on-delta (loss-free)", fontsize=8)
    fig.tight_layout()
    for d in ("figures/generated", "paper/figures"):
        fig.savefig(os.path.join(ROOT, d, "trace_characterization.pdf"))


if __name__ == "__main__":
    main()
