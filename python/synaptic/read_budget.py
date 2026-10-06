"""Exact numbered cold-Read page size, using the existing LF length prefix."""
MAX_READ_CHARS = 100_003


def numbered_overhead(start, end):
    total = 0
    cursor = start
    while cursor <= end:
        width = max(6, len(str(cursor)))
        stop = min(end, 10**width-1)
        total += (stop-cursor+1)*(width+1)
        cursor = stop+1
    return total


def numbered_chars(start, end, lengths):
    return lengths[end]-lengths[start-1]-1 + numbered_overhead(start, end)


def numbered_page_end(start, end, lengths):
    low, high = start, end
    while low < high:
        mid = (low+high+1)//2
        if numbered_chars(start, mid, lengths) <= MAX_READ_CHARS:
            low = mid
        else:
            high = mid-1
    return low
