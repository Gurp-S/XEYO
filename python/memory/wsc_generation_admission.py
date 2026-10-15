"""Generation publication is authorized by the fold caller, never by recovery."""


def retained_only(new_generation, cached, cursor):
    """Ordinary requests may reuse a verified same-cursor head or replay source."""
    if new_generation:
        return False, None
    if cached is not None and cached.head and cached.cursor == cursor:
        return True, cached
    return True, None
