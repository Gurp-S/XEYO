"""Free official Anthropic prediction; never send count requests to gateways."""
from urllib.parse import urlsplit


async def predict(client, messages, tools, abort):
    origin = urlsplit(client._base_url)
    if (origin.scheme != "https" or origin.netloc not in {"api.anthropic.com", "api.anthropic.com:443"}
            or origin.path not in {"", "/"} or origin.query or origin.fragment):
        return None
    from model.anthropic import httpx
    if httpx is None:
        return None
    from model._openai_common import get_shared_httpx_client
    from model.stream_io import abortable

    body = client._build_body(messages, tools, stream=False)
    payload = {key: body[key] for key in ("model", "messages", "system", "tools", "thinking", "tool_choice")
               if key in body}
    headers = {**client._headers(), "Accept": "application/json"}
    try:
        response = await abortable(get_shared_httpx_client(120.0).post(
            "https://api.anthropic.com/v1/messages/count_tokens", json=payload,
            headers=headers, timeout=10.0, follow_redirects=False), abort)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        value = response.json().get("input_tokens")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
