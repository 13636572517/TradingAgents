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
cd web && npm ci --prefer-offline --silent && npm run build --silent && cd ..

echo "==> [5/5] 重启 systemd 服务..."
sudo systemctl restart tradingagents-server tradingagents-celery tradingagents-beat
sleep 3
sudo systemctl is-active tradingagents-server tradingagents-celery tradingagents-beat

echo ""
echo "==> 部署完成！访问 https://trading.yusuan.xyz"
echo "==> 查看日志: sudo journalctl -u tradingagents-server -f"
