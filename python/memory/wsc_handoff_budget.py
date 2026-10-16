"""Existing usage limits shared by generation and continuation admission."""


def check_usage(budget):
    if budget.over_budget:
        raise ValueError('budget_usd')
    if budget.over_token_budget():
        raise ValueError('budget')
