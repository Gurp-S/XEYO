"""Validate the native reference's supported text/image input envelope.

Image transport bytes are not tokens. The official Flash Vision bound is
1024 per image; this is an upper estimate, not dimension-exact billing.
No image decoding, remote retrieval, or changes to provider input occur.
"""
from urllib.parse import urlsplit

IMAGE_TOKENS_UPPER = 1024
IMAGE_BASIS = 'deepseek_v41_text_reference_with_image_upper_estimate'


def supported(messages):
    for message in messages:
        content = message.get('content', '')
        if isinstance(content, (str, type(None))):
            blocks = [{'type': 'text', 'text': content or ''}]
        elif isinstance(content, list):
            blocks = content
        else:
            return False
        for block in blocks:
            if not isinstance(block, dict):
                return False
            if block.get('type') == 'text':
                text = block.get('text')
                if not isinstance(text, str) or any(marker in text for marker in ('<image>', '</image>', '<｜deepseek_image｜>')):
                    return False
            elif block.get('type') == 'image_url' and message.get('role') == 'user':
                image = block.get('image_url')
                if not isinstance(image, dict) or image.get('detail', 'auto') not in {'auto', 'low', 'high', 'original'}:
                    return False
                url = image.get('url')
                if not isinstance(url, str):
                    return False
                if url.startswith('data:image/'):
                    if ';base64,' not in url or not url.partition(';base64,')[2]:
                        return False
                else:
                    origin = urlsplit(url)
                    if origin.scheme not in {'https', 'http'} or not origin.netloc:
                        return False
            else:
                return False
    return True
