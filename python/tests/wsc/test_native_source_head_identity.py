from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

from memory import wsc_head_store as heads
from memory.wsc_source_layout import LEGACY, APPEND


def test_legacy_head_format_and_source_seal_are_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "1")
    rows = [{"role": "user", "content": "same facts"}]
    legacy = hashlib.sha1((json.dumps(rows[0], sort_keys=True, ensure_ascii=False) + "\x1e").encode()).hexdigest()
    assert heads.region_seal(rows, 1) == legacy
    heads.save("legacy-format", text="head", cwd="workspace", cursor=1, region_end=1, messages=rows)
    payload = json.loads(heads.path_for("legacy-format").read_text())
    assert "compression_source_layout" not in payload
    assert payload["seal"] == legacy


def test_native_head_identity_is_independent_in_concurrent_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "1")
    rows = [{"role": "user", "content": "identical source bytes"}]
    def run(index):
        mode = APPEND if index % 2 else LEGACY
        other = LEGACY if index % 2 else APPEND
        session = f"concurrent-layout-{index}"
        heads.save(session, text=f"head {index}", cwd="workspace", cursor=1, region_end=1,
                   messages=rows, source_layout=mode)
        assert heads.load(session, cwd="workspace", cursor=1, messages=rows, source_layout=mode).text == f"head {index}"
        assert heads.load(session, cwd="workspace", cursor=1, messages=rows, source_layout=other) is None
        return heads.region_seal(rows, 1, source_layout=mode)
    with ThreadPoolExecutor(max_workers=4) as pool:
        seals = list(pool.map(run, range(24)))
    assert len(set(seals)) == 2
