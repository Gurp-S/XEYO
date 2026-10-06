"""Read coverage is physical; expand coverage follows exact available bindings."""
from synaptic.coldstore import parse_reqs_payload


def bound_nodes(handle, bindings):
    if handle in bindings:
        return frozenset(bindings[handle])
    kind, _, payload = handle.partition('://')
    if kind == 'node':
        return frozenset(int(part.strip()) for part in payload.split(',') if part.strip().isdigit())
    if kind == 'reqs':
        span = parse_reqs_payload(payload)
        if span is not None:
            return frozenset(range(span[0], span[1] + 1))
    return frozenset()


def rendered_nodes(renderer, text, read_re):
    out = set()
    # Only expand returns all bound bodies. An origin extent attached to Read
    # describes later recovery; it cannot add bodies to the immediate slice.
    for handle in renderer.extract(text):
        if f'expand({handle})' in text:
            out.update(bound_nodes(handle, renderer.handle_nodes))
    reverse = renderer._reverse_index()
    first_reads = {first for _full, first in renderer._declared_extents(text)} if hasattr(renderer, '_declared_extents') else set()
    cache = getattr(renderer, '_coverage_cache', None)
    if cache is None:
        cache = {}
        object.__setattr__(renderer, '_coverage_cache', cache)
    for match in read_re.finditer(text):
        key = (match.group('path'), int(match.group('offset')), int(match.group('limit')))
        if key not in reverse and key not in first_reads:
            continue
        if key not in cache:
            start, end = key[1], key[1] + key[2] - 1
            cache[key] = frozenset(
                idx for handle, (lo, hi) in renderer.node_ranges.items()
                if start <= lo and hi <= end
                for idx in bound_nodes(handle, {})
            )
        out.update(cache[key])
    return frozenset(out)


def visible_reference_count(text, expand_re, read_re):
    """Count distinct visible reference mentions; not validity or actual use."""
    expands = {match.group(1) for match in expand_re.finditer(text)}
    reads = {(match.group('path'), int(match.group('offset')), int(match.group('limit')))
             for match in read_re.finditer(text)}
    return len(expands) + len(reads)
