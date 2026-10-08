"""Apply the configured full-request soft watermark to the first normal fold."""


def admit(working, account):
    from memory.wsc_watermark import soft_watermark_tokens
    limit = soft_watermark_tokens()
    tokens = int(getattr(working, "last_prompt_tokens", 0) or 0)
    if account is not None:
        account.update(first_soft_watermark=limit, first_input_tokens=tokens)
    return limit <= 0 or tokens >= limit
