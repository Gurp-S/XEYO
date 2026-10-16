"""One-run Zhipu transport for the existing WSC three-arm production trial.

No XEYO provider configuration changes. Same model/settings for every arm;
provider usage and conservative UTF-8 admission estimates are kept separate.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import httpx
from evals import wsc_ad_experiment as e
from evals.wsc_api_budget import admit, charge
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from model.openai_compat import OpenAICompatClient

MODEL = 'glm-5.3-flash'
BASE = 'https://open.bigmodel.cn/api/paas/v4'
CAPACITY = 1_000_000  # Conservative interpretation of the documented 1M.
RATES = {'input': 0.8, 'cached_input': 0.23, 'output': 2.8}
KEY_FILE = Path('C:/Users/48522/Desktop/GLM API.txt')


class Client(OpenAICompatClient):
    def __init__(self):
        super().__init__(api_key='not-sent', base_url=BASE, model=MODEL,
                         provider='zhipu', reasoning_effort='low')
        self.declare_context_limit(CAPACITY)

    def context_token_measure(self, source):
        return (len(e.canonical(source).encode('utf-8')) + 8192,
                'utf8_bytes_plus_8192_conservative_estimate')


class Frame(ProviderFrameModel):
    context_limit = CAPACITY

    def for_handoff(self, *, max_tokens):
        return Frame(self.calls, self.client, self.label, max_tokens, state=self.state)

    def body(self, messages, tools):
        body = super().body(messages, tools)
        body.update(thinking={'type': 'enabled'}, reasoning_effort='low', temperature=0.1)
        return body


def price(usage):
    prompt, output = usage['prompt_tokens'], usage['completion_tokens']
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens')
    assert 0 <= prompt and 0 <= output
    if cached is not None:
        assert 0 <= cached <= prompt
    # Absent cache details mean unknown, never a fabricated cache hit.
    hit = cached or 0
    return ((prompt-hit)*RATES['input'] + hit*RATES['cached_input'] + output*RATES['output'])/1e6


class Calls:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(1)
        self.key = KEY_FILE.read_text(encoding='utf-8-sig').strip()
        assert self.key and not any(c.isspace() for c in self.key), 'invalid_key_file_shape'
        self.report = {'provider': 'zhipu', 'model': MODEL, 'calls': [], 'branches': [],
                       'rates_cny_per_million': RATES, 'http_retries': 0,
                       'billing_basis': 'Provider usage times official public rates; not an invoice. Missing usage retains reservation.',
                       'token_estimation': 'UTF-8 bytes + 8192 for admission; not a GLM tokenizer.'}
        self.evaluation_stopped = False

    def save(self):
        e.write(e.ROOT/'run-report.json', self.report)

    async def call(self, body, label):
        from evals.wsc_elimination_faithful import EvaluationStop
        async with self.semaphore:
            if self.evaluation_stopped:
                raise EvaluationStop('evaluation_run_stopped')
            entry = None
            start = time.monotonic()
            try:
                from evals.wsc_semantic_production_trial import validate_wire
                validate_wire(body)
                assert body['model'] == MODEL and body['stream'] is False
                encoded = e.canonical(body).encode('utf-8')
                assert self.key.encode() not in encoded, 'credential_in_request'
                count = len(encoded) + 8192
                limit = body['max_tokens']
                assert count + limit <= CAPACITY, 'glm_capacity_estimate_exceeded'
                upper = (count*RATES['input'] + limit*RATES['output'])/1e6
                journal = json.loads(e.JOURNAL.read_text(encoding='utf-8'))
                admit(journal, upper)
                request = e.ROOT/(label+'-request.json')
                assert not request.exists(), 'No paid rerun'
                e.write(request, body)
                entry = {'label': label, 'admitted_cny_upper': upper, 'usage_observed': False,
                         'cost_estimate': upper, 'input_token_admission_estimate': count,
                         'request_sha256': hashlib.sha256(request.read_bytes()).hexdigest(),
                         'output_limit': limit, 'total_deadline_seconds': 180}
                self.report['calls'].append(entry)
                charge(journal, upper)
                journal['entries'].append(str(request)); e.write(e.JOURNAL, journal); self.save()
                print(json.dumps({'sending': label, 'admitted_cny_upper': upper}), flush=True)
                async with httpx.AsyncClient(trust_env=False,
                        timeout=httpx.Timeout(120, connect=20, write=40, pool=20),
                        transport=httpx.AsyncHTTPTransport(retries=0, trust_env=False)) as client:
                    response = await asyncio.wait_for(client.post(BASE+'/chat/completions',
                        content=encoded, headers={'Authorization': 'Bearer '+self.key,
                        'Content-Type': 'application/json'}), timeout=180)
                entry['status_code'] = response.status_code
                entry['response_headers'] = {k:v for k,v in response.headers.items()
                                             if k in {'x-request-id','request-id','retry-after','date'}}
                if response.is_error:
                    entry['error_body'] = response.text.replace(self.key, '[REDACTED]')[:4000]
                response.raise_for_status()
                answer = response.json()
                # Keep complete provider frames for exact continuation replay.
                entry['response'] = json.loads(e.canonical(answer).replace(self.key, '[REDACTED]'))
                usage = answer.get('usage')
                if usage and 'prompt_tokens' in usage and 'completion_tokens' in usage:
                    cost = price(usage)
                    entry.update(usage_observed=True, cost_estimate=cost)
                    journal = json.loads(e.JOURNAL.read_text(encoding='utf-8'))
                    charge(journal, cost-upper); e.write(e.JOURNAL, journal)
                    assert cost <= upper and cost <= 2.5, 'usage_exceeds_conservative_admission'
                assert answer.get('choices'), 'glm_missing_choices'
                return answer
            except BaseException as exc:
                self.evaluation_stopped = True
                reason = type(exc).__name__+': '+str(exc).replace(self.key, '[REDACTED]')[:500]
                if entry is not None: entry['error'] = reason
                self.report.update(stop_reason=reason, stopped_at=label)
                if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)): raise
                raise EvaluationStop(reason) from exc
            finally:
                if entry is not None: entry['elapsed_seconds'] = round(time.monotonic()-start, 3)
                self.save()


def configure():
    import evals.wsc_semantic_format_pilot as p
    e.CLIENT = Client()
    p.ProviderFrameModel = Frame


async def health():
    e.ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-glm-health-322')
    assert not e.ROOT.exists()
    e.ROOT.mkdir()
    configure()
    calls = Calls()
    body = Frame(calls, e.CLIENT, 'health', 512).body(
        [{'role': 'user', 'content': 'Reply with exactly API_OK.'}], [])
    answer = await calls.call(body, 'glm-health')
    choice = answer['choices'][0]
    calls.report['health_ok'] = choice['finish_reason'] == 'stop' and choice['message'].get('content','').strip() == 'API_OK'
    calls.save()
    print(json.dumps({'health_ok': calls.report['health_ok'], 'usage': answer.get('usage'),
                      'cost_estimate_cny': calls.report['calls'][0]['cost_estimate']}), flush=True)


async def trial():
    os.environ['WSC_SEMANTIC_TRIAL_RUN'] = 'wsc-glm-semantic-production-323'
    configure()
    from evals import wsc_semantic_production_trial as trial_module
    trial_module.ValidatedCalls = Calls
    await trial_module.main()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(health() if '--health' in sys.argv else trial())
