"""Test-only local provider address; production startup and routes are unchanged."""
import os
import asyncio
import gc
import io
import threading
import faulthandler
from pathlib import Path
from collections import Counter
from model.openai_compat import PROVIDER_PRESETS
from server.__main__ import main

if __name__ == '__main__':
    PROVIDER_PRESETS['local']['base_url'] = os.environ['XEYO_TEST_UPSTREAM']
    from server.app import app
    if Path(os.environ['XEYO_HOME']).parent.name.startswith('surfaces'):
        stack_file = (Path(os.environ['XEYO_HOME']).parent/'threads.log').open('a')
        faulthandler.dump_traceback_later(20, repeat=True, file=stack_file)

    @app.get('/__test__/diagnostics')
    async def diagnostics():
        objects = gc.get_objects()
        files = Counter(str(obj.name) for obj in objects if isinstance(obj, io.IOBase) and not obj.closed and hasattr(obj, 'name'))
        types = Counter(type(obj).__name__ for obj in objects)
        tasks = Counter(getattr(t.get_coro(), '__qualname__', type(t.get_coro()).__name__) for t in asyncio.all_tasks())
        return {'threads': len(threading.enumerate()), 'files': files.most_common(30),
                'types': types.most_common(30), 'tasks': tasks, 'pid': os.getpid()}

    main()
