"""Process-wide scheduling and complete per-execution accounting."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class ProviderScheduler:
    def __init__(self, capacity: int):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("provider concurrency must be a positive integer")
        self.capacity = capacity
        self._slots = threading.BoundedSemaphore(capacity)
        self._lock = threading.Lock()
        self.in_flight = 0
        self.peak_in_flight = 0
        self.queued = 0
        self.completed = 0
        self.queue_seconds: list[float] = []
        self.active_seconds: list[float] = []

    @contextmanager
    def slot(self):
        queued_at = time.monotonic()
        with self._lock:
            self.queued += 1
        with self._slots:
            acquired_at = time.monotonic()
            with self._lock:
                self.in_flight += 1
                self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
                self.queue_seconds.append(acquired_at - queued_at)
            try:
                yield
            finally:
                released_at = time.monotonic()
                with self._lock:
                    self.in_flight -= 1
                    self.completed += 1
                    self.active_seconds.append(released_at - acquired_at)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "capacity": self.capacity,
                "in_flight": self.in_flight,
                "peak_in_flight": self.peak_in_flight,
                "queued_total": self.queued,
                "completed_total": self.completed,
                "mean_queue_seconds": (
                    sum(self.queue_seconds) / len(self.queue_seconds)
                    if self.queue_seconds else 0.0
                ),
                "mean_active_seconds": (
                    sum(self.active_seconds) / len(self.active_seconds)
                    if self.active_seconds else 0.0
                ),
            }


class ScheduledProvider:
    """Transparent provider wrapper; every retry attempt also occupies a slot."""

    def __init__(self, inner, scheduler: ProviderScheduler):
        self.inner = inner
        self.scheduler = scheduler
        for name in ("name", "model", "simulated", "input_price", "output_price"):
            setattr(self, name, getattr(inner, name))

    def complete(self, system, payload, max_tokens, temperature, seed):
        with self.scheduler.slot():
            return self.inner.complete(system, payload, max_tokens, temperature, seed)
