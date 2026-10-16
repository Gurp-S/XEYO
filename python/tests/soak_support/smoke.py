import asyncio
import json
import sys
import httpx
from tests.soak_support.lab import Lab

async def run(lab):
    async with httpx.AsyncClient(base_url=lab.base, timeout=90) as c:
        r = await c.post('/v1/sessions', json={'workspace': str(lab.workspace)})
        r.raise_for_status()
        sid = r.json()['session_id']
        print('SESSION', sid, flush=True)
        body = dict(model='local', provider='local', base_url=lab.model_base, session_id=sid,
                    stream=True, workspace=str(lab.workspace), permission_mode='never',
                    messages=[dict(role='user', content='XEYO_SOAK smoke 2 1')])
        async with c.stream('POST', '/v1/chat/completions', json=body) as r:
            print('HTTP',r.status_code,flush=True)
            async for line in r.aiter_lines():
                if line.startswith('data:'):
                    print(line,flush=True)
        print((await c.get(f'/v1/sessions/{sid}/agents')).text,flush=True)

if __name__ == '__main__':
    lab = Lab(sys.argv[1])
    try:
        lab.start()
        asyncio.run(run(lab))
    finally:
        lab.close()
