#!/usr/bin/env bash
# deploy.sh — 在服务器上运行，拉取最新代码并重启服务（systemd 模式）
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

echo "==> [1/5] 拉取最新代码..."
git pull origin main
# Re-exec so the rest of the script runs from the newly pulled version
if [ -z "${_DEPLOY_RELOADED:-}" ]; then
    exec env _DEPLOY_RELOADED=1 bash "$0" "$@"
fi

echo "==> [2/5] 同步 systemd service 文件..."
SERVICES=(tradingagents-server tradingagents-celery tradingagents-beat)
CHANGED=0
for svc in "${SERVICES[@]}"; do
    if ! diff -q "$APP_DIR/${svc}.service" "/etc/systemd/system/${svc}.service" &>/dev/null; then
        sudo cp "$APP_DIR/${svc}.service" "/etc/systemd/system/${svc}.service"
        CHANGED=1
    fi
done
if [ "$CHANGED" -eq 1 ]; then
    sudo systemctl daemon-reload
    echo "    service 文件已更新"
fi

echo "==> [3/5] 安装 Python 依赖..."
source venv/bin/activate
pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -q -e .

echo "==> [4/5] 构建前端静态文件..."

# 保护①：源码入口 index.html 必须存在，缺失则从 git 恢复（避免 vite build 因
#           UNRESOLVED_ENTRY 失败、只产出 PWA 的 sw.js 而上线一个坏前端）
if [ ! -f web/index.html ]; then
    echo "    ⚠ web/index.html 缺失，尝试从 git 恢复..."
    git checkout -- web/index.html 2>/dev/null || true
fi
if [ ! -f web/index.html ]; then
    echo "    ✗ 错误: web/index.html 仍然缺失，无法构建前端" >&2
    exit 1
fi

cd web && npm ci --prefer-offline --silent && npm run build --silent && cd ..

# 保护②：构建后必须产出 dist/index.html，否则视为构建失败并中止部署
if [ ! -f web/dist/index.html ]; then
    echo "    ✗ 错误: 构建未产出 web/dist/index.html（vite build 很可能失败），中止部署以避免上线坏前端" >&2
    exit 1
fi
echo "    ✓ 前端构建完成，dist/index.html 已生成"

echo "==> [5/5] 重启 systemd 服务..."
sudo systemctl restart tradingagents-server tradingagents-celery tradingagents-beat
sleep 3
sudo systemctl is-active tradingagents-server tradingagents-celery tradingagents-beat

echo ""
echo "==> 部署完成！访问 https://trading.yusuan.xyz"
echo "==> 查看日志: sudo journalctl -u tradingagents-server -f"
