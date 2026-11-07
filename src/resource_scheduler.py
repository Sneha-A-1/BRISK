"""Compute tiers (edge gateway, fog server, cloud) and task placement.

Each tier is a pool of identical cores.  Two disciplines are supported:
  * 'edf'  : preemptive-resume priority (urgent before strategic), EDF inside a class
  * 'fifo' : non-preemptive first-come-first-served
The cloud's per-core speed is reduced by the background utilisation rho_bg(t),
derived from the Azure Functions 2019 per-minute invocation trace (processor-sharing
approximation, evaluated when a task starts or resumes).
"""
from __future__ import annotations

import heapq
import itertools

import numpy as np

from .task_model import Task, URGENT


class Tier:
    def __init__(self, name: str, cores: int, speed: float, discipline: str = "edf",
                 bg=None):
        self.name, self.cores, self.speed, self.disc = name, cores, speed, discipline
        self.bg = bg  # callable t -> background utilisation in [0,1)
        self.queue: list = []
        self.running: dict = {}  # core -> Task
        self._seq = itertools.count()
        self.busy_time = 0.0
        self.engine = None  # set by simulator (needs .schedule)

    # ------------------------------------------------------------------ rates
    def rate(self, t: float) -> float:
        r = self.speed
        if self.bg is not None:
            r *= max(1.0 - self.bg(t), 0.02)
        return r

    def _key(self, task: Task):
        if self.disc == "fifo":
            return (next(self._seq),)
        return (task.prio, task.deadline, next(self._seq))

    # ------------------------------------------------------------- operations
    def submit(self, t: float, task: Task) -> None:
        task.tier = self.name
        task.t_ready = t
        if task.remaining <= 0:
            task.remaining = task.work
        free = [c for c in range(self.cores) if c not in self.running]
        if free:
            self._start(t, task, free[0])
            return
        if self.disc == "edf" and task.prio == URGENT:
            # preempt the running strategic task with the latest deadline
            cand = [(tk.deadline, c) for c, tk in self.running.items() if tk.prio > task.prio]
            if cand:
                _, c = max(cand)
                victim = self.running.pop(c)
                done = (t - victim.t_start_seg) * victim.rate
                self.busy_time += t - victim.t_start_seg
                victim.remaining = max(victim.remaining - done, 0.0)
                victim.version += 1
                heapq.heappush(self.queue, (self._key(victim), victim))
                self._start(t, task, c)
                return
        heapq.heappush(self.queue, (self._key(task), task))

    def _start(self, t: float, task: Task, core: int) -> None:
        task.core = core
        task.rate = self.rate(t)
        task.t_start_seg = t
        if task.t_start < 0:
            task.t_start = t
        self.running[core] = task
        task.version += 1
        self.engine.schedule(t + task.remaining / task.rate, "task_done",
                             (self, task, task.version))

    def complete(self, t: float, task: Task, version: int) -> bool:
        if version != task.version or self.running.get(task.core) is not task:
            return False  # stale event (task was preempted)
        del self.running[task.core]
        self.busy_time += t - task.t_start_seg
        task.remaining = 0.0
        task.t_done = t
        if self.queue:
            _, nxt = heapq.heappop(self.queue)
            self._start(t, nxt, task.core)
        return True

    # -------------------------------------------------------------- estimates
    def estimate_finish(self, t: float, task: Task) -> float:
        """Estimated completion time if `task` were submitted at t (no reservation)."""
        r = self.rate(t)
        free = self.cores - len(self.running)
        if free > 0:
            return t + task.work / r
        if self.disc == "edf" and task.prio == URGENT and any(
                tk.prio > task.prio for tk in self.running.values()):
            return t + task.work / r
        ahead = 0.0
        for tk in self.running.values():
            if self.disc == "fifo" or tk.prio <= task.prio:
                ahead += max(tk.remaining - (t - tk.t_start_seg) * tk.rate, 0.0)
        key = (task.prio, task.deadline)
        for k, tk in self.queue:
            if self.disc == "fifo" or (tk.prio, tk.deadline) <= key:
                ahead += tk.remaining if tk.remaining > 0 else tk.work
        return t + ahead / (self.cores * r) + task.work / r


class AzureBackground:
    """rho_bg(t) = min(rho_mean * L(t + offset) / median(L), rho_max), L = per-minute
    Azure Functions invocations (14 days, wrapped)."""

    def __init__(self, minute_load: np.ndarray, rho_mean: float, rho_max: float,
                 offset_min: int):
        self.L = minute_load / np.median(minute_load)
        self.rho_mean, self.rho_max, self.off = rho_mean, rho_max, offset_min

    def __call__(self, t: float) -> float:
        i = (int(t // 60) + self.off) % len(self.L)
        return min(self.rho_mean * self.L[i], self.rho_max)


# -------------------------------------------------------------- placement
def place_task(policy: dict, task: Task, t: float, tiers: dict, links: dict) -> str:
    """Return the tier name for `task`.

    links[name] -> object with .estimate(t, bytes) giving one-way transfer delay
    (None for the local edge tier).
    """
    mode = policy["placement_urgent"] if task.prio == URGENT else policy["placement_strategic"]
    if mode in ("edge", "fog", "cloud"):
        return mode
    ect = {}
    for name, tier in tiers.items():
        if tier is None:
            continue
        lk = links.get(name)
        up = lk.estimate(t, task.b_in) if lk is not None else 0.0
        down = lk.estimate(t, task.b_out) if lk is not None else 0.0
        ect[name] = tier.estimate_finish(t + up, task) + down
    if mode == "min_ect":
        return min(ect, key=ect.get)
    if mode == "cost_feasible":
        # cheapest tier (order given by policy['tier_cost_order']) that meets the deadline
        # with a safety margin; otherwise the minimum-ECT tier.
        margin = policy.get("deadline_margin", 0.1) * (task.deadline - t)
        for name in policy["tier_cost_order"]:
            if name in ect and ect[name] <= task.deadline - margin:
                return name
        return min(ect, key=ect.get)
    raise ValueError(mode)
