#!/usr/bin/env bash
# backfill_progress.sh — 在服务器上运行，每 30 秒刷新一次 backfill 进度
# 用法: bash scripts/backfill_progress.sh
# 退出: Ctrl+C

TOTAL=5515
INTERVAL=${1:-30}

while true; do
    clear
    echo "======================================"
    echo " TradingAgents Backfill 进度监控"
    echo " $(date '+%Y-%m-%d %H:%M:%S')  (每 ${INTERVAL}s 刷新)"
    echo "======================================"

    OHLCV_SYMS=$(mysql -h127.0.0.1 -ugesp -pmCZ@20260101 tradingagents \
        -se "SELECT COUNT(DISTINCT symbol) FROM stock_ohlcv" 2>/dev/null)
    OHLCV_ROWS=$(mysql -h127.0.0.1 -ugesp -pmCZ@20260101 tradingagents \
        -se "SELECT COUNT(*) FROM stock_ohlcv" 2>/dev/null)
    FIN_SYMS=$(mysql -h127.0.0.1 -ugesp -pmCZ@20260101 tradingagents \
        -se "SELECT COUNT(DISTINCT symbol) FROM stock_financials" 2>/dev/null)
    FIN_ROWS=$(mysql -h127.0.0.1 -ugesp -pmCZ@20260101 tradingagents \
        -se "SELECT COUNT(*) FROM stock_financials" 2>/dev/null)

    OHLCV_PCT=$(awk "BEGIN {printf \"%.1f\", $OHLCV_SYMS / $TOTAL * 100}")
    FIN_PCT=$(awk "BEGIN {printf \"%.1f\", $FIN_SYMS / $TOTAL * 100}")

    echo ""
    echo "  OHLCV    : ${OHLCV_SYMS} / ${TOTAL} 股  (${OHLCV_PCT}%)  ${OHLCV_ROWS} 行"
    echo "  Financials: ${FIN_SYMS} / ${TOTAL} 股  (${FIN_PCT}%)  ${FIN_ROWS} 行"
    echo ""

    # 进度条
    BAR_WIDTH=40
    OHLCV_FILLED=$(awk "BEGIN {printf \"%d\", $BAR_WIDTH * $OHLCV_SYMS / $TOTAL}")
    OHLCV_EMPTY=$((BAR_WIDTH - OHLCV_FILLED))
    printf "  OHLCV     [%s%s] %s%%\n" \
        "$(printf '#%.0s' $(seq 1 $OHLCV_FILLED 2>/dev/null || echo ''))" \
        "$(printf '.%.0s' $(seq 1 $OHLCV_EMPTY 2>/dev/null || echo ''))" \
        "$OHLCV_PCT"

    FIN_FILLED=$(awk "BEGIN {printf \"%d\", $BAR_WIDTH * $FIN_SYMS / $TOTAL}")
    FIN_EMPTY=$((BAR_WIDTH - FIN_FILLED))
    printf "  Financials[%s%s] %s%%\n" \
        "$(printf '#%.0s' $(seq 1 $FIN_FILLED 2>/dev/null || echo ''))" \
        "$(printf '.%.0s' $(seq 1 $FIN_EMPTY 2>/dev/null || echo ''))" \
        "$FIN_PCT"

    echo ""
    echo "--- 内存 ---"
    free -h | grep Mem

    echo ""
    echo "--- Celery 最新日志 ---"
    sudo journalctl -u tradingagents-celery -n 5 --no-pager \
        | grep -E "(backfill|succeeded|failed|pending|already done|financial|ERROR)" \
        | sed 's/.*celery\[[0-9]*\]: //'

    echo ""
    echo "  按 Ctrl+C 退出  |  下次刷新: ${INTERVAL}s"
    sleep "$INTERVAL"
done
