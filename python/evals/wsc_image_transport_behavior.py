"""Identical pixels in two PNG encodings: transport bytes are not occupancy."""
import argparse
import base64
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re


def run(output, key_file, execute=False):
    from PIL import Image, ImageDraw, ImageFont
    from evals.client import chat
    import evals.client as eval_client
    from evals.wsc_drift_budget import Budget
    from model.deepseek import DeepSeekModelClient
    from memory.wsc_timing import request_measure
    output.mkdir(parents=True, exist_ok=False)
    picture = Image.new('RGB', (200, 200), 'white')
    ImageDraw.Draw(picture).text((24, 50), '137', font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 80), fill='black')
    pixels = hashlib.sha256(picture.tobytes()).hexdigest()
    budget, reports = Budget(total=0.4), []
    model = DeepSeekModelClient(api_key='not-sent', base_url='https://api.deepseek.com',
                               model='deepseek-flash', thinking='disabled')
    for label, compression in [('compressed', 9), ('uncompressed', 0)]:
        folder = output / label
        folder.mkdir()
        buffer = BytesIO()
        picture.save(buffer, format='PNG', compress_level=compression)
        raw = buffer.getvalue()
        assert hashlib.sha256(Image.open(BytesIO(raw)).convert('RGB').tobytes()).hexdigest() == pixels
        (folder / 'fixture.png').write_bytes(raw)
        messages = [{'role': 'user', 'content': [
            {'type': 'text', 'text': '读出图中的数字，仅输出JSON对象，字段number。'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')}}]}]
        body = model._build_body(messages, [], stream=False)
        body.update(max_tokens=64, temperature=0)
        measured = request_measure(messages, [], context_limit=1048576, model=model)
        # Old policy reproduces normalized source bytes/4, not generation options.
        from memory.token import token_len
        old = token_len(json.dumps(model.context_input(messages, []), ensure_ascii=False, separators=(',', ':')))
        report = {'label': label, 'pixel_sha256': pixels, 'image_bytes': len(raw),
                  'old_byte_estimate': old, 'reference_upper_estimate': measured.input_tokens,
                  'basis': measured.basis, 'compression_exercised': False}
        (folder / 'request.json').write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
        if execute:
            keys = re.findall(r'sk-[A-Za-z0-9_-]{16,}', key_file.read_text(encoding='utf-8-sig'))
            if len(keys) != 1: raise ValueError('key_file_format_ambiguous')
            entry = budget.admit(body, 128)
            prior_key, prior_url = os.environ.get('DEEPSEEK_API_KEY'), eval_client.BASE_URL
            try:
                os.environ['DEEPSEEK_API_KEY'] = keys[0]
                eval_client.BASE_URL = 'https://api.deepseek.com'
                captured = chat(messages, model='deepseek-flash', thinking='disabled', max_tokens=64,
                                temperature=0, retries=0, timeout=45, capture_wire=True)
                assert captured['request'] == body
                response = captured['response']
                (folder / 'response.json').write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
                budget.settle(entry, response.get('usage'))
                answer = response['choices'][0]['message'].get('content') or ''
                clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', answer.strip())
                value = json.loads(clean)
                report.update(answer=answer, acceptance=isinstance(value, dict) and value.get('number') == 137,
                              usage=response.get('usage'))
            except Exception as exc:
                report.update(error=type(exc).__name__, acceptance=False)
            finally:
                eval_client.BASE_URL = prior_url
                if prior_key is None: os.environ.pop('DEEPSEEK_API_KEY', None)
                else: os.environ['DEEPSEEK_API_KEY'] = prior_key
        reports.append(report)
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert reports[0]['reference_upper_estimate'] == reports[1]['reference_upper_estimate']
    summary = {'scope': __doc__, 'executed': execute, 'arms': reports,
               'cost_peak_rate_estimate': budget.spent_upper, 'budget_entries': budget.entries}
    (output / 'report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    summary = run(args.output, args.key_file, args.execute)
    print(json.dumps({'executed': summary['executed'], 'arms': summary['arms'],
                      'cost_peak_rate_estimate': summary['cost_peak_rate_estimate']}, ensure_ascii=False))
