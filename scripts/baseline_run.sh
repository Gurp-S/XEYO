#!/usr/bin/env bash
# baseline_run.sh — 在某个提交的临时 worktree 里跑选定测试（判归因用）。
#
#   ref 绿 + 工作树红 ⇒ 红来自这段改动；
#   ref 也红          ⇒ 红早于这段改动，别归因给它。
#
# 为什么不用 stash / checkout：工作树常年带 200+ 未提交文件，stash 会把他人的在制品一起
# 卷走。worktree 只新增临时目录 + .git/worktrees 元数据，**不动当前工作树**。
#
# 为什么基线默认不是 HEAD：本仓有活跃的**外部自动提交**（编辑被逐批 commit、偶发 merge
# 别人的分支）⇒ HEAD 随时可能已包含你正在归因的改动。默认 `REF=auto` 取台账
# （.xeyo/baseline_stamp.json）里记的最早一次 HEAD；没有台账则退回当前 HEAD。
# 每次运行都打印「当前 HEAD / 用的 ref / 用的 sha / reflog 尾三行」，并落进台账。
#
# 用法：
#   scripts/baseline_run.sh "tests/test_x.py -q"
#   scripts/baseline_run.sh "tests/wsc -k fold"
#   REF=f7544d8 scripts/baseline_run.sh "tests/test_x.py -q"   # 指定基线提交
#   KEEP=1 scripts/baseline_run.sh "tests/test_x.py -q"        # 保留临时树
set -u

PYTEST_ARGS="${1:--m 'not live'}"
PYTHON_EXE="${PYTHON_EXE:-py}"
PYTHON_FLAGS="${PYTHON_FLAGS:--3.11}"
REF="${REF:-auto}"

root="$(git rev-parse --show-toplevel)"
[ -n "$root" ] || { echo "[baseline] 不是 git 仓库" >&2; exit 2; }
head_now="$(git -C "$root" rev-parse --short HEAD)"
stamp="$root/.xeyo/baseline_stamp.json"

first_head=""
if [ -f "$stamp" ]; then
  first_head="$(grep -o '"first_head"[[:space:]]*:[[:space:]]*"[^"]*"' "$stamp" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
fi
if [ "$REF" = "auto" ]; then
  if [ -n "$first_head" ]; then REF="$first_head"; else REF="$head_now"; fi
fi
sha="$(git -C "$root" rev-parse --short "$REF")"
[ -n "$sha" ] || { echo "[baseline] 无法解析基线提交：$REF" >&2; exit 2; }

tmp="$(mktemp -d "${TMPDIR:-/tmp}/xeyo-baseline-XXXXXX")"

echo "[baseline] HEAD 现值：$head_now（本次基线 ref：$REF = $sha）"
echo "[baseline] reflog 尾三行（HEAD 在你干活期间是否移动，看这里）："
git -C "$root" reflog -3 | sed 's/^/[baseline]     /'
echo "[baseline] 不改当前工作树（未提交改动原样留着）；下列动作只读该提交："
echo "[baseline]   1) git worktree add --detach $tmp $sha"
echo "[baseline]   2) 在 $tmp/python 跑 $PYTHON_EXE $PYTHON_FLAGS -m pytest -q -p no:cacheprovider $PYTEST_ARGS"
if [ "${KEEP:-0}" = "1" ]; then
  echo "[baseline]   3) KEEP=1：跑完保留临时树（自行清理：git worktree remove --force $tmp）"
else
  echo "[baseline]   3) git worktree remove --force $tmp"
fi

git -C "$root" worktree add --detach "$tmp" "$sha" >/dev/null || { echo "[baseline] worktree add 失败" >&2; exit 2; }

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
log="$(mktemp)"
# shellcheck disable=SC2086
"$PYTHON_EXE" $PYTHON_FLAGS -m pytest -q -p no:cacheprovider $PYTEST_ARGS 2>&1 | tee "$log"
code="${PIPESTATUS[0]}"
# 基线里根本没有这个文件（新增测试）⇒ 红不是"产品回归"，结论不成立。
missing=0
if grep -qE "no tests ran|file or directory not found" "$log"; then missing=1; fi
rm -f "$log"

# 台账：first_head 只记一次（= 这套工作开始前的那一版），供下次 REF=auto 使用。
[ -n "$first_head" ] || first_head="$head_now"
mkdir -p "$(dirname "$stamp")"
cat > "$stamp" <<JSON
{
  "first_head": "$first_head",
  "head_now": "$head_now",
  "used_ref": "$REF",
  "used_sha": "$sha",
  "exit_code": $code,
  "args": "$PYTEST_ARGS",
  "ts": "$(date '+%Y-%m-%dT%H:%M:%S')"
}
JSON
echo "[baseline] 台账已更新：$stamp（first_head=$first_head）"

if [ "$code" -eq 0 ]; then
  echo "[baseline] 基线（$sha）绿 ⇒ 这次红来自未提交改动"
else
  echo "[baseline] 基线（$sha）同样红（退出码 $code）⇒ 红早于未提交改动，别归因给本次改动"
fi
exit "$code"
