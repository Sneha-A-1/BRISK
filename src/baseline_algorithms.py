"""Baseline policies (all run on the same simulator, workload and metrics).

CLOUD-PER   Periodic reporting; every task executed in the cloud; FIFO queues.
            Conventional cloud-centric smart-farming pipeline (e.g. the cloud baseline
            of Alharbi & Aldossary, IEEE Access 2021).
EDGE-PER    Periodic reporting; urgent verification at the gateway (preemptive EDF);
            strategic analytics in the cloud.  Static edge-fog-cloud split.
SOD-PT      Send-on-delta (dual-prediction, constant predictor) with a fixed tolerance
            [Santini & Roemer 2006; Dias et al. survey]; the gateway decides urgent
            events immediately from point estimates; static placement.
SOD-PULL    Send-on-delta with fixed tolerance + interval-based verification; all nodes
            permanently in LoRaWAN Class B so that any uncertain zone member can be
            pulled; deadline-aware minimum-ECT placement for every task.  This is the
            strongest *decoupled* design: retrieval tolerances are set independently of
            urgency, and the network configuration is static.
"""

COMMON = {
    "discipline": "edf",
    "tier_cost_order": ["cloud", "fog", "edge"],
    "deadline_margin": 0.1,
}

BASELINES = {
    "CLOUD-PER": {**COMMON, "retrieval": "periodic", "verify": "point",
                  "placement_urgent": "cloud", "placement_strategic": "cloud",
                  "discipline": "fifo", "class_b": "none", "validity": "heartbeat"},
    "EDGE-PER": {**COMMON, "retrieval": "periodic", "verify": "point",
                 "placement_urgent": "edge", "placement_strategic": "cloud",
                 "class_b": "none", "validity": "heartbeat"},
    "SOD-PT": {**COMMON, "retrieval": "sod_fixed", "verify": "point",
               "placement_urgent": "edge", "placement_strategic": "cloud",
               "class_b": "none", "validity": "heartbeat"},
    "SOD-PULL": {**COMMON, "retrieval": "sod_fixed", "verify": "interval_pull",
                 "pull_select": "all", "placement_urgent": "min_ect",
                 "placement_strategic": "min_ect", "class_b": "all", "validity": "heartbeat"},
}
