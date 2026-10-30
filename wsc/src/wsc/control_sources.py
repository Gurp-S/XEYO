"""Mechanical control declarations shared by invalidation and view retention.

The predicate is kept as a thin alias so every consumer keeps its import while
the grading rules live in `control_grading`.
"""
from .control_grading import control_grade, is_control_source

__all__ = ['control_grade', 'is_control_source']
