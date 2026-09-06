#!/bin/sh
# 容器内补丁脚本（POSIX sh）：tmux + curl + uv
set -e
if tmux -V >/dev/null 2>&1 && curl --version >/dev/null 2>&1 && uvx --version >/dev/null 2>&1; then
    echo ALL-PRESENT
    exit 0
fi
export DEBIAN_FRONTEND=noninteractive
i=1
while [ $i -le 3 ]; do
    apt-get update -qq >/dev/null 2>&1 && break
    sleep 5
    i=$((i+1))
done
apt-get install -y -qq tmux curl >/dev/null 2>&1 || true
if ! curl --version >/dev/null 2>&1; then
    echo "WARN: curl still missing"
fi
if ! uvx --version >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || pip install uv >/dev/null 2>&1 || pip3 install uv >/dev/null 2>&1 || true
fi
export PATH="/root/.local/bin:$PATH"
tmux -V
curl --version | head -1
uvx --version
