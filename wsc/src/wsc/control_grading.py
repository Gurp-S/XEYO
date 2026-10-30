"""Control sources are graded, not binary.

`is_control_source` answers "may this row steer behaviour?"; downstream
retention and projection also need to know *how* it steers: host policy
(system/developer), operator instruction (user), or an explicit declaration
(`control=True`) carried by any other role. Flattening the three loses the
difference between a host rule and a replayed operator message, which is why
grading lives here rather than in each consumer.

Precedence is role first: a row that claims both `role='user'` and
`control=True` is an operator message, because the role is what the producer
actually asserted.
"""
GRADES = ('host', 'operator', 'declared')

_HOST_ROLES = frozenset(('system', 'developer'))


def control_grade(row):
    role = row.get('role')
    if role in _HOST_ROLES:
        return 'host'
    if role == 'user':
        return 'operator'
    if row.get('control') is True:
        return 'declared'
    return None


def is_control_source(row):
    return control_grade(row) is not None


def apply_control(value, row):
    """Record the control grade on a tool result without rewriting its role.

    The role states who produced the text; control states whether that text may
    steer behaviour. Overwriting the role (the previous behaviour) destroyed the
    producer fact to express the control fact.
    """
    grade = control_grade(row)
    if grade is None:
        return value
    from dataclasses import replace
    return replace(value, control=grade)
