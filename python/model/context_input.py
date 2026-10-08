"""Input fields of an encoded request; no credentials or generation options.

This is a structural view, not a token count. Keeping it on the real encoder
path accounts for provider-specific tool/result, system and media transforms.
"""


def from_body(body):
    return {key: body[key] for key in ("messages", "system", "tools") if key in body}
