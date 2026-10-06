"""Bounded older-input prefix scenario; no claim of vendor cache retention."""
from collections import deque

from evals.wsc_prefix_accounting import shared_tokens


class RecentPrefixes:
    def __init__(self, capacity=32):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("invalid prefix history capacity")
        self.history = deque(maxlen=capacity)

    def observe(self, body):
        latest = shared_tokens(self.history[-1], body) if self.history else 0
        best, age = latest, 1 if self.history else None
        for distance, previous in enumerate(reversed(self.history), 1):
            hit = shared_tokens(previous, body)
            if hit > best:
                best, age = hit, distance
        result = dict(latest_input_hit=latest, recent_input_hit=best,
                      extra_hit=best-latest, best_request_age=age,
                      retained_inputs=len(self.history), capacity=self.history.maxlen)
        self.history.append(body)
        return result
