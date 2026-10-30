"""Bounded lexical partitions, without ranking, omission or rewritten text."""
from .contracts import require


def word_character(char):
    # Common identifier/number/URL characters. This is a mechanical alphabet,
    # not a recognizer for specific hashes, file names or task evidence.
    return char.isalnum() or char in "_-./+@%="


def ranges(text, max_chars, *, policy="fixed"):
    require(type(max_chars) is int and max_chars > 0, "span_size_invalid")
    require(policy in {"fixed", "word"}, "span_boundary_policy_invalid")
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if policy == "word" and end < len(text) and word_character(text[end - 1]) and word_character(text[end]):
            boundary = end
            while boundary > start and word_character(text[boundary - 1]):
                boundary -= 1
            # An over-limit uninterrupted run must still respect the byte-
            # independent character bound; it is never discarded or enlarged.
            if boundary > start:
                end = boundary
        yield start, end
        start = end
