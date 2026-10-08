#!/usr/bin/env bash
# baseline_run.sh — 在 HEAD 提交的临时 worktree 里跑选定测试（判归因用）。
#
# 回答"这条红是不是未提交改动造成的"：
#   HEAD 绿 + 工作树红  ⇒ 红来自未提交改动；
#   HEAD 也红           ⇒ 红早于本次改动，别归因给它。
#
# 为什么不用 stash / checkout：工作树常年带 200+ 未提交文件，stash 会把他人的在制品
# 一起卷走。worktree 只新增临时目录 + .git/worktrees 元数据，**不动当前工作树**。
# 纪律（XEYO.md 禁区）：动手前先把要执行的 git 命令打出来（下面第一段就是）。
#
# 用法：
#   scripts/baseline_run.sh "tests/test_x.py -q"
#   scripts/baseline_run.sh "tests/wsc -k fold"
#   KEEP=1 scripts/baseline_run.sh "tests/test_x.py -q"   # 保留临时树
set -u

PYTEST_ARGS="${1:--m 'not live'}"
PYTHON_EXE="${PYTHON_EXE:-py}"
PYTHON_FLAGS="${PYTHON_FLAGS:--3.11}"

root="$(git rev-parse --show-toplevel)"
[ -n "$root" ] || { echo "[baseline] 不是 git 仓库" >&2; exit 2; }
head="$(git -C "$root" rev-parse --short HEAD)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/xeyo-baseline-XXXXXX")"

echo "[baseline] 不改当前工作树（未提交改动原样留着）；下列动作只读 HEAD 提交："
echo "[baseline]   1) git worktree add --detach $tmp $head"
echo "[baseline]   2) 在 $tmp/python 跑 $PYTHON_EXE $PYTHON_FLAGS -m pytest -q -p no:cacheprovider $PYTEST_ARGS"
if [ "${KEEP:-0}" = "1" ]; then
  echo "[baseline]   3) KEEP=1：跑完保留临时树（自行清理：git worktree remove --force $tmp）"
else
  echo "[baseline]   3) git worktree remove --force $tmp"
fi

git -C "$root" worktree add --detach "$tmp" HEAD >/dev/null || { echo "[baseline] worktree add 失败" >&2; exit 2; }

cleanup() {
  if [ "${KEEP:-0}" = "1" ]; then
    echo "[baseline] 保留临时树：$tmp"
  else
    git -C "$root" worktree remove --force "$tmp" >/dev/null
    echo "[baseline] 已移除临时树"
  fi
}
trap cleanup EXIT

cd "$tmp/python" || exit 2
# shellcheck disable=SC2086
"$PYTHON_EXE" $PYTHON_FLAGS -m pytest -q -p no:cacheprovider $PYTEST_ARGS
code=$?

if [ "$code" -eq 0 ]; then
  echo "[baseline] 基线（HEAD $head）绿 ⇒ 这次红来自未提交改动"
else
  echo "[baseline] 基线（HEAD $head）同样红（退出码 $code）⇒ 红早于未提交改动，别归因给本次改动"
fi
exit "$code"
