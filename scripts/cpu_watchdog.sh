#!/usr/bin/env bash
# cpu_watchdog.sh — CPU 使用率超过 70% 时自动停掉肇事服务
# 由 cron 每分钟调用一次，保护服务器上其他服务不受影响。
#
# 阈值: 总 CPU 使用率 > 70%（即 idle < 30%）
# 动作: 停掉最高 CPU 消费进程所属的 systemd 服务
# 白名单: 永远不会被停掉的关键服务

set -euo pipefail

# ── 配置 ────────────────────────────────────────────────────────────────────────
CPU_THRESHOLD=70          # CPU 使用率超过此值则触发
CHECK_COUNT_FILE="/tmp/cpu_watchdog_count"     # 连续超阈值计数
MAX_CHECKS=5              # 连续 5 次（5 分钟）超阈值才动手，避免误杀短暂峰值
LOG_TAG="cpu-watchdog"

# 白名单：这些服务永远不会被停掉
WHITELIST_SERVICES=(
    "mysql"
    "redis-server"
    "nginx"
    "sshd"
    "systemd-journald"
    "systemd-logind"
    "systemd-resolved"
    "cron"
    "dbus"
    "rsyslog"
)

# ── 日志 ────────────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | systemd-cat -t "$LOG_TAG" -p info; }
warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | systemd-cat -t "$LOG_TAG" -p warning; }

# ── 获取当前 CPU 使用率 ────────────────────────────────────────────────────────
get_cpu_usage() {
    # 使用 top 快照获取 us+sy 的总和
    top -b -n2 -d0.5 2>/dev/null \
        | grep -E '^%Cpu' \
        | tail -1 \
        | awk '{
            # 格式: %Cpu(s):  us,  sy,  ni,  id,  wa,  hi,  si,  st
            us = $2; gsub(/[^0-9.]/, "", us)
            sy = $4; gsub(/[^0-9.]/, "", sy)
            print us + sy
        }'
}

# ── 检查进程是否属于白名单服务 ────────────────────────────────────────────────
is_whitelisted() {
    local pid=$1
    local cgroup
    cgroup=$(cat "/proc/$pid/cgroup" 2>/dev/null | head -1 || true)
    for svc in "${WHITELIST_SERVICES[@]}"; do
        if echo "$cgroup" | grep -q "$svc"; then
            return 0
        fi
    done
    # Also check by process name
    local pname
    pname=$(ps -p "$pid" -o comm= 2>/dev/null || true)
    for svc in "${WHITELIST_SERVICES[@]}"; do
        if [ "$pname" = "$svc" ]; then
            return 0
        fi
    done
    return 1
}

# ── 找出最高 CPU 的进程及其所属 systemd 服务 ──────────────────────────────────
find_culprit_service() {
    # 获取 CPU 最高的非内核进程（跳过 kworker, kthread 等）
    local top_pid top_pname top_cpu
    read -r top_pid top_cpu top_pname < <(
        ps aux --sort=-pcpu --no-headers 2>/dev/null \
            | awk '!/^root.*\[.*\]/ && $3 > 10 {print $2, $3, $11}' \
            | head -1
    )

    if [ -z "$top_pid" ]; then
        return 1
    fi

    # 查找该 PID 所属的 systemd 单元
    local unit
    unit=$(systemctl status "$top_pid" 2>/dev/null \
        | grep -oP '(?<=[/\s])[^/\s]+\.service' \
        | head -1 || true)

    if [ -z "$unit" ]; then
        # 尝试通过 cgroup 查找
        unit=$(cat "/proc/$top_pid/cgroup" 2>/dev/null \
            | grep -oP '[^/]+\.service' \
            | head -1 || true)
    fi

    echo "$top_pid" "$top_cpu" "$top_pname" "$unit"
}

# ── 主逻辑 ──────────────────────────────────────────────────────────────────────

current_cpu=$(get_cpu_usage)
current_cpu_int=$(printf "%.0f" "$current_cpu")

if [ "$current_cpu_int" -lt "$CPU_THRESHOLD" ]; then
    # CPU 正常 — 重置计数
    echo 0 > "$CHECK_COUNT_FILE" 2>/dev/null || true
    exit 0
fi

# CPU 超阈值 — 累加计数
count=$(cat "$CHECK_COUNT_FILE" 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" > "$CHECK_COUNT_FILE"

if [ "$count" -lt "$MAX_CHECKS" ]; then
    log "CPU ${current_cpu_int}% > ${CPU_THRESHOLD}% (连续第 ${count}/${MAX_CHECKS} 次)，继续观察"
    exit 0
fi

# 连续超阈值达到上限 — 找出肇事者
read -r culprit_pid culprit_cpu culprit_name culprit_unit < <(find_culprit_service || echo "" "" "" "")

if [ -z "$culprit_pid" ]; then
    warn "CPU ${current_cpu_int}% 持续超标，但未找到高 CPU 用户进程（可能全是系统进程）"
    echo 0 > "$CHECK_COUNT_FILE"
    exit 0
fi

# 检查白名单
if is_whitelisted "$culprit_pid"; then
    warn "CPU ${current_cpu_int}% 持续超标，但最高消费进程 [$culprit_name (PID=$culprit_pid, CPU=${culprit_cpu}%)] 在白名单中，跳过"
    echo 0 > "$CHECK_COUNT_FILE"
    exit 0
fi

# 执行停止操作
if [ -n "$culprit_unit" ] && systemctl is-active --quiet "$culprit_unit" 2>/dev/null; then
    warn "CPU ${current_cpu_int}% 持续超标 ${MAX_CHECKS} 分钟，停掉服务: $culprit_unit (进程: $culprit_name, PID=$culprit_pid, CPU=${culprit_cpu}%)"
    sudo systemctl stop "$culprit_unit" 2>/dev/null || true
    sudo systemctl disable "$culprit_unit" 2>/dev/null || true
    warn "已停用 $culprit_unit — 需要手动检查后重新启用"
else
    # 无法找到 systemd 单元，直接 kill 进程
    warn "CPU ${current_cpu_int}% 持续超标 ${MAX_CHECKS} 分钟，杀死进程: $culprit_name (PID=$culprit_pid, CPU=${culprit_cpu}%)"
    kill -15 "$culprit_pid" 2>/dev/null || true
    sleep 2
    kill -9 "$culprit_pid" 2>/dev/null || true
    warn "已杀死 $culprit_name (PID=$culprit_pid)"
fi

# 重置计数
echo 0 > "$CHECK_COUNT_FILE"

# 等 3 秒再查一次 CPU，确认恢复
sleep 3
final_cpu=$(get_cpu_usage)
final_cpu_int=$(printf "%.0f" "$final_cpu")
log "操作后 CPU: ${final_cpu_int}%"
