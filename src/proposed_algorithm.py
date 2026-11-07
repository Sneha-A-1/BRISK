"""BRISK: Bounded Retrieval with Interval-verified Spatial checks and slacK-aware
placement -- the proposed coordinated retrieval/orchestration policy.

Components (switches used by the ablation study):
  C1 heartbeat='proximity'   urgency-proximity heartbeat: nodes whose root-zone VW is
                             close to a decision threshold refresh the gateway replica
                             often (H_min); distant nodes rarely (H_max).  Tolerances
                             follow the same proximity rule (proximity=True).
  C2 retry='deadline_spread' alarm retransmissions spaced to span the alarm deadline
                             (time diversity against bursty node-side losses).
  C3 validity='loss_aware'   members with recent sequence-number gaps are treated as
                             uncertain in the interval quorum test.
  C4 verify='interval_point' interval (bounded-error) zone quorum; if inconclusive the
                             gateway decides immediately from point estimates (no pulls).
  C5 placement               urgent: minimum estimated completion time across tiers;
                             strategic: cheapest tier that meets the deadline.
  C6 energy_queue=True       per-node energy virtual queue stretches tolerance and
                             heartbeat when the node overspends its energy budget.
Optional (evaluated as a variant): class_b='watch' + verify='interval_pull'.
"""
from .baseline_algorithms import COMMON

BRISK = {**COMMON, "retrieval": "brisk", "heartbeat": "proximity", "retry": "deadline_spread",
         "verify": "interval_point", "pull_select": "reliable",
         "placement_urgent": "min_ect", "placement_strategic": "cost_feasible",
         "class_b": "none", "validity": "loss_aware", "proximity": True,
         "watch_tighten": True, "energy_queue": True}

ABLATIONS = {
    "BRISK": BRISK,
    "BRISK-fixedHB": {**BRISK, "heartbeat": "fixed", "proximity": False},
    "BRISK-stdRetry": {**BRISK, "retry": "standard"},
    "BRISK-noLoss": {**BRISK, "validity": "heartbeat"},
    "BRISK-noEQ": {**BRISK, "energy_queue": False},
    "BRISK-edgeOnly": {**BRISK, "placement_urgent": "edge", "placement_strategic": "edge"},
    "BRISK+Watch": {**BRISK, "class_b": "watch", "verify": "interval_pull"},
}
