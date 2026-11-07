"""Task model.  A task is tau = (a, d, w, b_in, b_out, p): arrival time, absolute
deadline, work (seconds on a reference core), input/output bytes, priority class
(0 = urgent, 1 = strategic)."""
from __future__ import annotations

from dataclasses import dataclass, field
import itertools

_ids = itertools.count()

URGENT, STRATEGIC = 0, 1


@dataclass
class Task:
    kind: str            # 'verify' | 'weather' | 'map'
    arrival: float       # a_i  (s): time the task is released at the gateway controller
    deadline: float      # d_i  (s, absolute)
    work: float          # w_i  (reference-core seconds)
    b_in: int            # bytes shipped to the executing tier
    b_out: int           # bytes returned to the gateway (actuation point)
    prio: int            # 0 urgent, 1 strategic
    origin: float = 0.0  # time the triggering observation was sampled (latency origin)
    meta: dict = field(default_factory=dict)
    tid: int = field(default_factory=lambda: next(_ids))
    # runtime fields
    tier: str = ""
    remaining: float = 0.0
    t_ready: float = 0.0   # arrival at the executing tier
    t_start: float = -1.0
    t_start_seg: float = 0.0
    t_done: float = -1.0
    t_delivered: float = -1.0
    version: int = 0
    rate: float = 1.0
    core: int = -1
