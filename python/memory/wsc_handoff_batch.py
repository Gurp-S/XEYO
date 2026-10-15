"""Mechanical batch protocol of the isolated declaration capability set."""


def rejection(uses, read_names):
    declarations = [use for use in uses if use.name == 'TodoWrite']
    error = None
    if declarations and len(uses) != 1:
        error = 'handoff_mixed_declaration'
    elif any(use.name not in read_names and use.name != 'TodoWrite' for use in uses):
        error = 'handoff_invalid_call'
    if error is None:
        return None
    return {'error': error, 'declaration_exclusive': True,
            'calls': [{'id': use.id, 'name': use.name} for use in uses],
            'executed_call_ids': []}
