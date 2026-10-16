"""Evaluation-only budget policy; unlimited totals still preserve call limits."""
import math


def unlimited_total(journal):
    return journal.get('unlimited_total_budget') is True


def admit(journal, upper, *, run_spent=0, run_ceiling=None):
    limit = journal.get('per_call_limit_cny', 2.5)
    if not math.isfinite(upper) or upper < 0 or upper > limit:
        raise ValueError('evaluation_budget_exceeded')
    if unlimited_total(journal):
        return
    if upper > journal['remaining_rate_estimate']:
        raise ValueError('evaluation_budget_exceeded')
    if run_ceiling is not None and run_spent + upper > run_ceiling:
        raise ValueError('evaluation_budget_exceeded')


def charge(journal, delta):
    """Reserve or settle costs without discarding earlier unknown reservations."""
    if not math.isfinite(delta):
        raise ValueError('invalid_evaluation_cost')
    journal['spent_rate_estimate'] += delta
    if not unlimited_total(journal):
        journal['remaining_rate_estimate'] -= delta
