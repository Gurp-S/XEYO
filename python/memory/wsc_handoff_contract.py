"""One parsed state for all guards; transition proposals retain their own schema."""
from copy import deepcopy


def normalized(raw, parsed):
    # Raw shape/identity checks precede this boundary. Defaults and canonical
    # identities come exclusively from the native parser used by TodoWrite.
    return {**deepcopy(raw), 'todos': [item.to_dict() for item in parsed.todos],
            'checkpoint': deepcopy(parsed.checkpoint), 'merge': parsed.merge}
