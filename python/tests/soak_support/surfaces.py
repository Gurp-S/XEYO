"""Owned UI test lab and a real HTTP proxy with explicit fault controls."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
import httpx
import uvicorn
from tests.soak_support.lab import Lab, port


def app_for(lab):
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=180) as client:
            app.state.client = client
            yield
    app = FastAPI(lifespan=lifespan)
    app.state.drop = 0
    app.state.requests = []

    @app.post('/__test__/fault')
    async def fault(request: Request):
        body = await request.json()
        app.state.drop = body.get('drop_after', 0)
        if body.get('crash'):
            await asyncio.to_thread(lab.crash)
        if body.get('restart'):
            await asyncio.to_thread(lab.restart)
        return {'ok': True}

    @app.get('/__test__/requests')
    async def requests():
        return app.state.requests

    @app.api_route('/{path:path}', methods=['GET', 'POST', 'DELETE', 'PUT', 'PATCH', 'OPTIONS'])
    async def proxy(path: str, request: Request):
        app.state.requests.append({'method': request.method, 'path': path, 'query': str(request.url.query)})
        client = app.state.client
        headers = {k: v for k, v in request.headers.items() if k not in ('host', 'content-length', 'connection')}
        req = client.build_request(request.method, lab.base+'/'+path, params=request.query_params,
                                   content=await request.body(), headers=headers)
        try:
            upstream = await client.send(req, stream=True)
        except httpx.HTTPError:
            return Response('backend unavailable', status_code=503)
        response_headers = {k: v for k, v in upstream.headers.items() if k not in ('content-length', 'transfer-encoding', 'connection', 'content-encoding')}
        drop = app.state.drop if path == 'v1/chat/completions' else 0
        if drop:
            app.state.drop = 0
        async def chunks():
            count = 0
            try:
                async for line in upstream.aiter_lines():
                    yield (line+'\n').encode()
                    if line.startswith('data:'):
                        count += 1
                        if drop and count >= drop:
                            return
            finally:
                await upstream.aclose()
        if 'text/event-stream' in upstream.headers.get('content-type', ''):
            return StreamingResponse(chunks(), status_code=upstream.status_code, headers=response_headers)
        body = await upstream.aread()
        await upstream.aclose()
        return Response(body, status_code=upstream.status_code, headers=response_headers)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    lab = Lab(args.directory)
    try:
        lab.start()
        proxy_port = port()
        data = json.loads((lab.directory/'lab.json').read_text())
        data['proxy'] = f'http://127.0.0.1:{proxy_port}'
        data['proxy_port_file'] = str(lab.directory/'proxy-port.json')
        (lab.directory/'surfaces.json').write_text(json.dumps(data, indent=2))
        (lab.directory/'proxy-port.json').write_text(json.dumps({'port': proxy_port}))
        print(json.dumps(data), flush=True)
        uvicorn.run(app_for(lab), host='127.0.0.1', port=proxy_port, log_level='warning')
    finally:
        lab.close()
