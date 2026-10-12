"""Image transport size cannot become text occupancy in native Flash."""
from copy import deepcopy

import pytest

from model.deepseek_count import measure
from model.deepseek_media_count import IMAGE_BASIS


def counted(content, role='user'):
    return measure({'messages': [{'role': role, 'content': content}]},
                   model='deepseek-flash', base_url='https://api.deepseek.com', thinking='disabled')


def image(url='data:image/png;base64,AAAA'):
    return {'type': 'image_url', 'image_url': {'url': url}}


def test_encoded_bytes_do_not_determine_occupancy_and_source_is_immutable():
    content = [{'type': 'text', 'text': 'current observation'}, image()]
    original = deepcopy(content)
    first = counted(content)
    large = deepcopy(content)
    large[1]['image_url']['url'] = 'data:image/png;base64,' + 'A' * 1000000
    assert counted(large) == first and first[1] == IMAGE_BASIS
    assert 1024 <= first[0] < 1100 and content == original


def test_each_image_is_counted_and_text_blocks_stay_in_order():
    one = counted([{'type': 'text', 'text': 'left'}, image(), {'type': 'text', 'text': 'right'}])
    two = counted([{'type': 'text', 'text': 'left'}, image(), image(), {'type': 'text', 'text': 'right'}])
    assert 1024 <= two[0] - one[0] < 1030
    text = counted([{'type': 'text', 'text': 'left'}, {'type': 'text', 'text': 'right'}])
    assert text[1] == 'deepseek_v41_text_reference_estimate'


@pytest.mark.parametrize('content,role', [
    ([image()], 'assistant'), ([image()], 'system'), ([image()], 'tool'),
    ([{'type': 'audio', 'data': 'AAAA'}], 'user'),
    ([image('xeyo-media://unmaterialized')], 'user'),
    ([image('file-api-unknown')], 'user'),
    ([image('data:image/png;base64,')], 'user'),
])
def test_unsupported_envelopes_remain_explicit_fallback(content, role):
    assert counted(content, role) is None


def test_remote_image_uses_upper_bound_without_fetching(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('No network retrieval is part of counting')
    monkeypatch.setattr('urllib.request.urlopen', unexpected)
    result = counted([image('https://example.invalid/picture.png')])
    assert result[1] == IMAGE_BASIS and 1024 <= result[0] < 1100


@pytest.mark.asyncio
async def test_valid_image_transport_cannot_force_a_false_capacity_fold():
    import base64
    from io import BytesIO
    import json
    from types import SimpleNamespace
    from PIL import Image
    from engine.abort import AbortController
    from model.deepseek import DeepSeekModelClient
    from memory.token import token_len
    from memory.wsc_counted_input import CountedInput
    from memory.wsc_request_timing import prepare_counted
    buffer = BytesIO()
    Image.new('RGB', (200, 200), 'white').save(buffer, format='PNG', compress_level=0)
    url = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')
    messages = [{'role': 'user', 'content': [image(url) for _ in range(30)]}]
    original = deepcopy(messages)
    model = DeepSeekModelClient(api_key='not-sent', base_url='https://api.deepseek.com',
                               model='deepseek-flash', thinking='disabled')
    old = token_len(json.dumps(model.context_input(messages, []), ensure_ascii=False, separators=(',', ':')))
    assert old * 100 >= 1048576 * 85
    def unexpected():
        raise AssertionError('Image transport is not a capacity trigger')
    working = SimpleNamespace(compact_cursor=0, wsc_timing_state={})
    prepared = await prepare_counted(messages, [], working, context_limit=1048576,
        build=lambda rows: rows, render=lambda rows, text: rows,
        compact=unexpected, model=CountedInput(model, AbortController()))
    assert prepared.facts['before']['basis'] == IMAGE_BASIS
    assert prepared.facts['automatic_attempts'] == 0
    assert prepared.facts['before']['emitted_tokens'] < 32000
    assert prepared.messages == messages == original
