#!/usr/bin/env bash
# diagnose_db.sh — 检查数据库配置和数据一致性
set -euo pipefail

echo "=== 1. 检查 .env.prod 中的 DATABASE_URL ==="
grep DATABASE_URL /opt/tradingagents/.env.prod || echo "未找到 DATABASE_URL"

echo ""
echo "=== 2. 检查 systemd service 的 EnvironmentFile ==="
grep EnvironmentFile /etc/systemd/system/tradingagents-*.service

echo ""
echo "=== 3. 检查实际运行的进程的环境变量 ==="
CELERY_PID=$(pgrep -f 'celery.*worker' | head -1)
if [ -n "$CELERY_PID" ]; then
    echo "Celery PID: $CELERY_PID"
    sudo cat /proc/$CELERY_PID/environ | tr '\0' '\n' | grep DATABASE_URL || echo "DATABASE_URL 未设置！"
else
    echo "Celery worker 未运行"
fi

echo ""
echo "=== 4. 检查 SQLite 数据库文件 ==="
ls -lh /opt/tradingagents/*.db 2>/dev/null || echo "无 .db 文件"

echo ""
echo "=== 5. 检查 MySQL analyses 表 ==="
mysql -h127.0.0.1 -ugesp -p'mCZ@20260101' tradingagents -e "
SELECT COUNT(*) as total_analyses FROM analyses;
SELECT owner_id, COUNT(*) as count FROM analyses GROUP BY owner_id;
SELECT status, COUNT(*) as count FROM analyses GROUP BY status;
" 2>/dev/null || echo "无法连接 MySQL"

echo ""
echo "=== 6. 检查最近的 Celery 日志（数据库相关） ==="
sudo journalctl -u tradingagents-celery -n 50 --no-pager | grep -i "database\|mysql\|sqlite\|DATABASE_URL" | tail -10 || echo "无相关日志"

echo ""
echo "=== 7. 检查最新的服务启动日志 ==="
sudo journalctl -u tradingagents-server -n 20 --no-pager | grep -i "DATABASE_URL\|startup" | tail -5 || echo "无相关日志"
