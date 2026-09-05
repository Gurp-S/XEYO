"""P0b 尾部/全量回归 · 无缓冲 + 小批次分离执行（独立于 harness 控制台）。

- 默认（无参）：固定 98 文件尾部清单；
- ``--all``：自动发现 ``tests/`` 全部测试文件（排除 simulator/live 探针），
  分批跑完 —— 一次覆盖验收「前半段 991」+「尾部」，供 8.2/8.3 一并闭环。

替换单次大调用：拆成 BATCH_SIZE 一批，每批一个独立 pytest 进程
（一个隐藏控制台 + 自身进程组 + BREAKAWAY，耐控制台 Ctrl+C / kill-on-close Job，
且子进程不再为孙进程新开窗口 → 根治「一直闪」）。

价值：
- 无缓冲（PYTHONUNBUFFERED=1 + 逐行刷文件日志 + ``-s``）：任何死亡点前一行
  输出都已落盘，不再出现「空日志 + exit 0」的失速假象；
- 小批次解耦：某一批哪怕被环境杀掉，其余批照常跑完 → 总能拿到**部分绿清点**，
  而不是整段丢失；
- 每批独立 JUnit XML，批间互不影响。

用法（由 ``run-pytest-p0b-tail.bat`` 经 Task Scheduler 调起，或手动双击
``run-pytest-p0b-tail-runner.bat``）：
    py -3.11 run_p0b_tail_batches.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYDIR = ROOT / "python"
LOGS = ROOT / "logs"
SENTINEL = ROOT / "logs" / "pytest-p0b-tail.done"
BATCH_SIZE = 10

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

#: 让 pytest 自带**一个隐藏控制台**（而非无控制台）。测试内再 spawn 子进程时
#: 会继承这个隐藏控制台 → 不再为每个子进程新开控制台窗口（根治「一直闪」）。
_HIDE_SI = subprocess.STARTUPINFO()
_HIDE_SI.dwFlags |= subprocess.STARTF_USESHOWWINDOW
_HIDE_SI.wShowWindow = subprocess.SW_HIDE

# ── 与 run-pytest-p0b-tail-runner.bat 一致的 98 文件清单（勿删） ────────────────
FILES = """tests/test_multi_agent_p1_toolpath.py
tests/test_multi_agent_p2_agent_ops.py
tests/test_multi_agent_stream_flush.py
tests/test_multiagent_hardening.py
tests/test_nested_instructions_t17.py
tests/test_nightshift.py
tests/test_notebook_edit_tool.py
tests/test_permission_ask_resume.py
tests/test_permission_grants.py
tests/test_permission_policy.py
tests/test_permission_t3.py
tests/test_permissions.py
tests/test_plan_flow.py
tests/test_port_file_health.py
tests/test_power_hierarchy_hardening.py
tests/test_pre_llm_inject.py
tests/test_process_narration.py
tests/test_project_cow_c2_gain.py
tests/test_prompt_engineering_opt.py
tests/test_protected_metadata.py
tests/test_quality_plan.py
tests/test_query_engine_submit.py
tests/test_query_loop_echo.py
tests/test_query_loop_plain.py
tests/test_read_symbol.py
tests/test_read_vision.py
tests/test_record_transcript.py
tests/test_remote_channel.py
tests/test_repeat_guard.py
tests/test_resume_from_disk.py
tests/test_rewind_api.py
tests/test_rewind_chat_only_and_recovery.py
tests/test_rewind_checkpoint_cursor.py
tests/test_rewind_discard_rotated.py
tests/test_rewind_file_tools.py
tests/test_rewind_hash_soft_conflict.py
tests/test_rewind_hotpath.py
tests/test_rewind_journal.py
tests/test_rewind_models.py
tests/test_rewind_query_engine.py
tests/test_rewind_revision.py
tests/test_rewind_service.py
tests/test_rewind_workspace_ops.py
tests/test_runtime_c2.py
tests/test_runtime_mode.py
tests/test_rwlock_t2.py
tests/test_sandbox_hardening.py
tests/test_screenshot_tool.py
tests/test_search_noise.py
tests/test_security_gate.py
tests/test_server_api.py
tests/test_server_fake_provider.py
tests/test_server_hardening.py
tests/test_session_continue.py
tests/test_session_cwd_isolation.py
tests/test_session_extend_turns.py
tests/test_session_md.py
tests/test_session_messages_restore.py
tests/test_session_pool_busy.py
tests/test_session_pool_eviction.py
tests/test_session_presence.py
tests/test_session_title.py
tests/test_shadow_git.py
tests/test_side_mode.py
tests/test_simple_functionality.py
tests/test_skills_api.py
tests/test_slash.py
tests/test_spill.py
tests/test_string_utils.py
tests/test_subagent_memory.py
tests/test_subagent_meta.py
tests/test_system_date.py
tests/test_task_state.py
tests/test_todo_restore.py
tests/test_todo_write_tool.py
tests/test_tool_orchestration.py
tests/test_tool_perf.py
tests/test_tool_progress.py
tests/test_transcript_blobs.py
tests/test_transcript_rotation.py
tests/test_turn_detach_reattach.py
tests/test_unclosed_tool_use_t4.py
tests/test_usage_combine.py
tests/test_usage_ledger.py
tests/test_vendor_models.py
tests/test_vendor_usage.py
tests/test_web_tools.py
tests/test_workspace_fs.py
tests/test_workspace_git.py
tests/test_workspace_lock.py
tests/test_workspace_restore_scoped_perf.py
tests/test_workspace_restore.py
tests/test_workspace_revision.py
tests/test_workspace_scope.py
tests/test_write_policy.py
tests/test_xeyo_ui_policy.py
tests/test_xeyo_ui_tool.py
tests/test_xml_tool_call.py""".splitlines()


def batches(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


#: --all 模式排除的目录（live 探针/生成物），与 _verify_remaining.py 全量忽略一致。
_SKIP_PARTS = {"simulator", "__pycache__", ".venv", ".pytest_cache"}


def discover_all() -> list[str]:
    """自动发现 ``tests/`` 下全部 pytest 测试文件（batched 全量运行）。

    只收 ``tests/`` 树内的 ``test_*.py``；跳过 simulator（live 探针）、
    ``__pycache__``/``.venv``/``.pytest_cache``。排除 ``conftest.py``/``bootstrap.py``
    （非测试）。结果排序保证确定性。
    """
    out: list[str] = []
    for p in PYDIR.rglob("test_*.py"):
        rel = p.relative_to(PYDIR).as_posix()
        if not rel.startswith("tests/"):
            continue
        parts = rel.split("/")
        if any(part in _SKIP_PARTS for part in parts):
            continue
        if p.name in ("conftest.py", "bootstrap.py"):
            continue
        out.append(rel)
    return sorted(out)


def _spawn(argv: list[str], log: Path) -> subprocess.Popen:
    """带**一个隐藏控制台**的子进程（SW_HIDE），输出逐行刷到 log（无缓冲）。

    刻意不给 CREATE_NO_WINDOW：pytest 有（隐藏）控制台后，测试内再 spawn 的
    子进程会继承它而非新开窗口 → 杜绝反复闪黑框。
    """
    fh = open(log, "w", encoding="utf-8", buffering=1)
    common = dict(
        cwd=str(PYDIR),
        stdin=subprocess.DEVNULL,
        stdout=fh,
        stderr=subprocess.STDOUT,
        startupinfo=_HIDE_SI,
    )
    flags_full = CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    try:
        return subprocess.Popen(argv, creationflags=flags_full, **common)
    except OSError:
        return subprocess.Popen(argv, creationflags=CREATE_NEW_PROCESS_GROUP, **common)


def main() -> int:
    LOGS.mkdir(exist_ok=True)
    root_failures = open(LOGS / "pytest-p0b-tail.summary.txt", "w", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"  # 让 pytest 的进度/输出逐行落盘
    env["PYTHONIOENCODING"] = "utf-8"

    # 模式：--all/全部 → 自动发现 tests/ 全量；否则 → 固定 98 文件尾部清单。
    argv_mode = {a.strip().lower() for a in sys.argv[1:]}
    all_mode = bool({"all", "--all", "-a"} & argv_mode)
    target_files = discover_all() if all_mode else FILES
    mode_name = "ALL" if all_mode else "TAIL"

    bs = batches(target_files, BATCH_SIZE)
    overall = 0
    root_failures.write(f"XEYO P0b {mode_name} @ {datetime.now(timezone.utc).isoformat()}\n")
    root_failures.write(
        f"mode={mode_name} files={len(target_files)} batches={len(bs)} batch_size={BATCH_SIZE}\n"
    )
    root_failures.flush()

    for idx, group in enumerate(bs, 1):
        log = LOGS / f"p0b-batch{idx:02d}.log"
        xml = LOGS / f"p0b-batch{idx:02d}.xml"
        argv = [
            sys.executable,
            "-m",
            "pytest",
            *group,
            "-q",
            "-p",
            "no:cacheprovider",
            "-s",
            "--tb=long",
            "--no-header",
            "-rf",
            "--junitxml",
            str(xml),
        ]
        root_failures.write(f"\n=== batch {idx}/{len(bs)} [{len(group)} files] ===\n")
        root_failures.flush()
        proc = _spawn(argv, log)
        try:
            code = proc.wait()
        except BaseException:  # 含 KeyboardInterrupt：子进程独立，仍等它收尾
            try:
                code = proc.wait()
            except BaseException:
                code = 0
        overall |= 0 if code == 0 else 1
        root_failures.write(f"batch {idx}: exit={code} → log={log.name} xml={xml.name}\n")
        root_failures.flush()

    root_failures.write(f"\nOVERALL exit={'PASS' if overall == 0 else 'FAIL'} ({overall})\n")
    root_failures.close()
    try:
        SENTINEL.write_text(f"done exit={overall}\n", encoding="ascii")
    except OSError:
        pass
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
