import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.query_engine import build_default_engine


async def main():
	eng = build_default_engine(model_backend="fake")
	async for ev in eng.submit("echo:hi"):
		print(ev)
	print("--- messages ---")
	for m in eng.get_messages():
		print(m.role, m.content)


if __name__ == "__main__":
	asyncio.run(main())
