"""Resolve an undeclared window from this client's exact vendor model row.

No model-name fallback, global connection cache, or transcript mutation.
Successful metadata is reused per connection. A failed lookup can be
retried at the next submit boundary, never inside the model/tool loop.
"""
from __future__ import annotations

import asyncio
import hashlib


def _connection(model):
    from model.deepseek import DeepSeekModelClient
    from model.openai_compat import OpenAICompatClient
    if not isinstance(model, (DeepSeekModelClient, OpenAICompatClient)):
        return None
    provider = 'deepseek' if isinstance(model, DeepSeekModelClient) else model._provider
    return (provider, model._base_url, model._model,
            hashlib.sha256(model._api_key.encode('utf-8')).hexdigest())


async def ensure_capacity(model, abort):
    """Called before projection/admission; an aborted lookup cannot publish."""
    connection = _connection(model)
    if connection is None:
        return
    previous = getattr(model, '_wsc_capacity_connection', None)
    if previous is not None and previous != connection:
        if getattr(model, 'context_capacity_basis', None) == 'vendor_models':
            model.context_limit = None
        model._wsc_capacity_connection = None
    # A session/env declaration or an existing authoritative usage wins.
    if getattr(model, 'context_limit', None):
        return
    if getattr(model, '_wsc_capacity_connection', None) == connection:
        return
    from model.vendor_models import fetch_vendor_models
    from model.stream_io import abortable
    response = await abortable(asyncio.to_thread(fetch_vendor_models,
        api_key=model._api_key, provider=connection[0], base_url=connection[1]), abort)
    abort.raise_if_aborted()
    # Connection/config may have changed while the network worker was running.
    if _connection(model) != connection or getattr(model, 'context_limit', None):
        return
    if response.get('vendor_ok'):
        model._wsc_capacity_connection = connection
    rows = response.get('data', []) if response.get('vendor_ok') else []
    matches = [row for row in rows if row.get('id') == connection[2]]
    capacity = matches[0].get('context_length') if len(matches) == 1 else None
    if isinstance(capacity, int) and not isinstance(capacity, bool) and capacity > 0:
        model.context_limit = capacity
        model.context_capacity_basis = 'vendor_models'
    else:
        model.context_capacity_basis = 'unknown'
