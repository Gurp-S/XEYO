"""Documented native output defaults; never mutates provider requests.

Source: https://api-docs.deepseek.com/api/create-chat-completion/ (2026-10-13).
Maximum supported output is a separate quantity, not the service default.
Default enabled after explicit-request and total-window A/B; zero opts out.
"""
import os
from urllib.parse import urlsplit

ENV = 'XEYO_DEEPSEEK_DEFAULT_OUTPUT_RESERVE'


def measure(*, configured, model, base_url, thinking, reasoning_effort=None):
    from model.context_input import output_limit_from_body
    explicit = output_limit_from_body({'max_tokens': configured})
    if explicit is not None:
        return explicit, 'provider_request_output_limit'
    if configured is not None or os.environ.get(ENV, '1').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return None, 'unknown'
    origin = urlsplit(base_url)
    if (origin.scheme != 'https' or origin.netloc not in {'api.deepseek.com', 'api.deepseek.com:443'}
            or origin.path not in {'', '/', '/v1'} or origin.query or origin.fragment
            or model != 'deepseek-flash'):
        return None, 'unknown'
    if thinking == 'disabled':
        return 8192, 'provider_documented_default_output_limit'
    if thinking == 'enabled':
        return (131072 if reasoning_effort == 'max' else 65536), 'provider_documented_default_output_limit'
    return None, 'unknown'
