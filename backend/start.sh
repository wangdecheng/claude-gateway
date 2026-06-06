#!/usr/bin/env bash
#
# start.sh — 后端启动脚本
# 强制使用 8082 端口启动；如果端口被占用则先杀掉占用进程
#

set -euo pipefail

PORT=8082
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Cloude Gateway Backend ==="

# 1) 检查端口占用
pids=$(lsof -ti :"$PORT" 2>/dev/null || true)

if [ -n "$pids" ]; then
    echo "⚠  端口 $PORT 被以下 PID 占用: $(echo "$pids" | tr '\n' ' ')"
    echo "   正在终止..."
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1

    # 二次确认
    remaining=$(lsof -ti :"$PORT" 2>/dev/null || true)
    if [ -n "$remaining" ]; then
        echo "❌ 无法释放端口 $PORT, 残留 PID: $(echo "$remaining" | tr '\n' ' ')"
        exit 1
    fi
    echo "✓  端口 $PORT 已释放"
else
    echo "✓  端口 $PORT 空闲"
fi

# 2) 启动服务
cd "$SCRIPT_DIR"
echo "🚀 启动 FastAPI → http://localhost:$PORT"
exec uv run uvicorn server:app --host 0.0.0.0 --port "$PORT" --reload
