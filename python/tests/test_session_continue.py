import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

from engine.query_engine import build_default_engine


@pytest.mark.asyncio
async def test_session_continue():
	eng = build_default_engine(model_backend="fake")
	async for _ in eng.submit("hello"):
		pass
	n1 = len(eng.mutable_messages)
	async for _ in eng.submit("again"):
		pass
	assert len(eng.mutable_messages) > n1


if __name__ == "__main__":
	import pytest

	raise SystemExit(pytest.main([__file__, "-q"]))
