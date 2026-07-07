#!/usr/bin/env bash
# cpu_watchdog.sh — CPU 使用率超过 70% 时自动停掉肇事服务
# 由 cron 每分钟调用一次，保护服务器上其他服务不受影响。
#
# 阈值: 总 CPU 使用率 > 70%（即 idle < 30%）
# 动作: 停掉最高 CPU 消费进程所属的 systemd 服务
# 白名单: 永远不会被停掉的关键服务
#
# 优化版（相比旧版）：
#   - 不再 fork `top`（旧版 top -b -n2 -d0.5 会挂起 ~1 秒并消耗排序开销），
#     改为直接读 /proc/stat 两次采样，间隔仅 0.1 秒。
#   - `ps` 定位肇事进程仅在确认动手（连续 5 次超标）时才调用，
#     正常观察路径零额外进程开销。
#   - 定位 systemd 单元优先从 /proc/$pid/cgroup 解析，去掉 `systemctl status` fork。
#   正常路径：约 0.2 秒墙钟 + 几乎为零的 CPU（仅两次读 /proc/stat）。

set -euo pipefail

# ── 配置 ────────────────────────────────────────────────────────────────────────
CPU_THRESHOLD=70          # CPU 使用率超过此值则触发
CHECK_COUNT_FILE="/tmp/cpu_watchdog_count"     # 连续超阈值计数
MAX_CHECKS=5              # 连续 5 次（5 分钟）超阈值才动手，避免误杀短暂峰值
SAMPLE_SLEEP=0.1          # /proc/stat 两次采样间隔（秒）
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
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | systemd-cat -t "$LOG_TAG" -p info; }
warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | systemd-cat -t "$LOG_TAG" -p warning; }

# ── 获取当前 CPU 使用率（100 - idle）────────────────────────────────────────────
get_cpu_usage() {
    local line1 line2
    line1=$(grep -m1 '^cpu ' /proc/stat) || { echo 0; return; }
    sleep "$SAMPLE_SLEEP"
    line2=$(grep -m1 '^cpu ' /proc/stat) || { echo 0; return; }

    local f1 f2
    f1=($line1)   # cpu user nice system idle iowait irq softirq steal guest guest_nice
    f2=($line2)

    local idle1=$(( ${f1[4]:-0} + ${f1[5]:-0} ))
    local idle2=$(( ${f2[4]:-0} + ${f2[5]:-0} ))

    local total1=0 total2=0 i
    for ((i = 1; i < ${#f1[@]}; i++)); do total1=$((total1 + ${f1[i]:-0})); done
    for ((i = 1; i < ${#f2[@]}; i++)); do total2=$((total2 + ${f2[i]:-0})); done

    local dtotal=$((total2 - total1)) didle=$((idle2 - idle1))
    if [ "$dtotal" -le 0 ]; then echo 0; return; fi

    local usage=$(( (100 * (dtotal - didle)) / dtotal ))
    echo "$usage"
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
# 仅在确认动手时调用（每分钟最多一次），开销可忽略。
find_culprit_service() {
    local top_pid top_pname top_cpu
    read -r top_pid top_cpu top_pname < <(
        ps -eo pid=,pcpu=,comm= --sort=-pcpu --no-headers 2>/dev/null \
            | awk '$2 > 10 {print $1, $2, $3; exit}'
    )

    if [ -z "$top_pid" ]; then
        return 1
    fi

    # 优先从 cgroup 解析 systemd 单元（避免 fork systemctl status）
    local unit
    unit=$(grep -oP '[^/]+\.service' "/proc/$top_pid/cgroup" 2>/dev/null | head -1 || true)

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

# 连续超阈值达到上限 — 找出肇事者（仅此处调用 ps）
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
