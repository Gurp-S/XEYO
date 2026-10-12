"""Pinned official V4.1 text reference estimate; never a provider receipt.

Only native Flash aliases have evidence. Image counts use a separate upper
estimate; unknown templates fall back. No downloads or remote code execution,
history-dependent adjustment of the estimate.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

MODELS = frozenset({'deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp'})
BASIS = 'deepseek_v41_text_reference_estimate'
TOKENIZER_SHA256 = 'c90dfa01249db1be4245780a052ede752e1361c612ac6d08e2bdada7d599476b'
ENCODER_SHA256 = '502bdaec8a3fd88ebc24c4721a7038fbe42f2063c664638127056107920035c1'


@lru_cache(maxsize=1)
def tokenizer():
    root = Path(__file__).parent / 'reference_v41'
    for filename, expected in [('tokenizer.json', TOKENIZER_SHA256), ('encoding.py', ENCODER_SHA256)]:
        if hashlib.sha256((root / filename).read_bytes()).hexdigest() != expected:
            raise ValueError('reference_asset_hash_mismatch')
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(root / 'tokenizer.json'))


def measure(source, *, model, base_url, thinking, reasoning_effort=None):
    origin = urlsplit(base_url)
    if (model not in MODELS or thinking not in {'enabled', 'disabled'}
            or origin.scheme != 'https' or origin.netloc not in {'api.deepseek.com', 'api.deepseek.com:443'}
            or origin.path not in {'', '/', '/v1'} or origin.query or origin.fragment):
        return None
    messages = source.get('messages')
    if not isinstance(messages, list) or not messages:
        return None
    from model.deepseek_media_count import supported, IMAGE_TOKENS_UPPER, IMAGE_BASIS
    if not supported(messages):
        return None
    try:
        backend = tokenizer()
        from model.reference_v41.encoding import encode_messages
        copied = deepcopy(messages)
        if source.get('tools'):
            if copied[0]['role'] != 'system':
                copied.insert(0, {'role': 'system', 'content': ''})
            copied[0]['tools'] = deepcopy(source['tools'])
        text, media = encode_messages(copied, thinking_mode='thinking' if thinking == 'enabled' else 'chat',
                                       reasoning_effort=reasoning_effort, return_multi_modal_data=True)
        images = media['images']
        count = len(backend.encode(text, add_special_tokens=False).ids)
        return count + len(images) * IMAGE_TOKENS_UPPER, IMAGE_BASIS if images else BASIS
    except (ImportError, OSError, ValueError, TypeError, KeyError, AssertionError, NotImplementedError, RuntimeError):
        return None
