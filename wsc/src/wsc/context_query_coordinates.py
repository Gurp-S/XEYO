"""Opt-in mechanical defaults; no interpretation of ranges or content."""


def with_json_pointer_units(args, *, enabled=False):
    if (enabled and type(args) is dict and args.get('operation') == 'json_pointer'
            and type(args.get('reference')) is str
            and args['reference'].startswith('result:') and 'units' not in args):
        return {**args, 'units': 'json_pointer'}
    return args
