"""Stream cleanup cannot discard usage already returned by the provider."""


async def close_and_account(stream, client, account):
    try:
        await stream.aclose()
    finally:
        account(getattr(client, 'last_usage', None))
