// web/src/pages/Settings.tsx
import { useEffect, useState, useCallback } from "react"
import { api } from "../api/client"
import type { Settings, SettingsUpdate, ModelOption, Provider, TestResult } from "../types"

// ── JoinQuant status panel ────────────────────────────────────────────────────
function JQPanel() {
  const [status, setStatus] = useState<{
    connected: boolean; username?: string; queries_remaining?: number; error?: string
  } | null>(null)
  const [checking, setChecking] = useState(false)

  const check = async () => {
    setChecking(true)
    try { setStatus(await api.getJQStatus()) }
    catch { setStatus({ connected: false, error: "无法连接到后端" }) }
    finally { setChecking(false) }
  }

  return (
    <div className="mt-8 bg-surface border border-border rounded-lg p-4 text-sm">
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-white font-medium">聚宽 JoinQuant（A股主数据源）</span>
          <span className="ml-2 text-gray-500 text-xs">需在 joinquant.com/default/index/sdk 申请开通</span>
        </div>
        <button
          onClick={check}
          disabled={checking}
          className="text-xs px-3 py-1 rounded border border-border text-gray-400 hover:border-accent hover:text-accent disabled:opacity-50 transition-colors"
        >
          {checking ? "检测中…" : "检测连接"}
        </button>
      </div>
      {status && (
        <div className={`rounded p-2.5 text-xs ${
          status.connected
            ? "bg-buy/10 border border-buy/30 text-buy"
            : "bg-red-500/10 border border-red-500/30 text-red-400"
        }`}>
          {status.connected
            ? `✓ 已连接 (${status.username})，今日剩余查询：${status.queries_remaining} 次`
            : `✗ 未连接 — ${status.error ?? "请先在聚宽官网申请 SDK 权限"}`}
        </div>
      )}
      {!status && (
        <p className="text-gray-600 text-xs">
          点击「检测连接」验证聚宽 API 权限是否已开通
        </p>
      )}
    </div>
  )
}

// ── Futu OpenD status panel ───────────────────────────────────────────────────
function FutuPanel() {
  const [status, setStatus] = useState<{ connected: boolean; error?: string } | null>(null)
  const [checking, setChecking] = useState(false)

  // phone verification state
  const [verifyStep, setVerifyStep] = useState<"idle" | "requesting" | "code_sent" | "submitting" | "done">("idle")
  const [verifyCode, setVerifyCode] = useState("")
  const [verifyMsg, setVerifyMsg] = useState<{ success: boolean; text: string } | null>(null)

  const check = async () => {
    setChecking(true)
    try {
      const s = await api.getFutuStatus()
      setStatus(s)
    } catch {
      setStatus({ connected: false, error: "无法连接到后端服务" })
    } finally {
      setChecking(false)
    }
  }

  const requestCode = async () => {
    setVerifyStep("requesting")
    setVerifyMsg(null)
    try {
      const r = await api.futuVerifyRequest()
      if (r.success) {
        setVerifyStep("code_sent")
        setVerifyMsg({ success: true, text: "验证码已发送到注册手机，请在 5 分钟内输入" })
      } else {
        setVerifyStep("idle")
        setVerifyMsg({ success: false, text: r.message || "发送失败" })
      }
    } catch {
      setVerifyStep("idle")
      setVerifyMsg({ success: false, text: "请求失败，请检查 FutuOpenD 是否正在运行" })
    }
  }

  const submitCode = async () => {
    if (!verifyCode.trim()) return
    setVerifyStep("submitting")
    setVerifyMsg(null)
    try {
      const r = await api.futuVerifySubmit(verifyCode.trim())
      if (r.success) {
        setVerifyStep("done")
        setVerifyMsg({ success: true, text: "✓ 验证成功！FutuOpenD 已重新认证，港股/美股数据恢复正常" })
        setStatus(null) // reset so user can recheck
      } else {
        setVerifyStep("code_sent")
        setVerifyMsg({ success: false, text: r.message || "验证码错误，请重试" })
      }
    } catch {
      setVerifyStep("code_sent")
      setVerifyMsg({ success: false, text: "提交失败，请重试" })
    }
  }

  const needsVerify = status && !status.connected

  return (
    <div className="mt-8 bg-surface border border-border rounded-lg p-4 text-sm">
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-white font-medium">富途 OpenD（美股/港股数据）</span>
          <span className="ml-2 text-gray-500 text-xs">需本地运行 Futu App 并开启 OpenD</span>
        </div>
        <button
          onClick={check}
          disabled={checking}
          className="text-xs px-3 py-1 rounded border border-border text-gray-400 hover:border-accent hover:text-accent disabled:opacity-50 transition-colors"
        >
          {checking ? "检测中…" : "检测连接"}
        </button>
      </div>

      {status && (
        <div className={`rounded p-2.5 text-xs ${
          status.connected
            ? "bg-buy/10 border border-buy/30 text-buy"
            : "bg-red-500/10 border border-red-500/30 text-red-400"
        }`}>
          {status.connected
            ? "✓ OpenD 已连接，美股/港股数据正常"
            : `✗ OpenD 未连接 — ${status.error ?? "请确认 Futu App 已启动并开启 OpenD"}`}
        </div>
      )}

      {!status && (
        <div className="text-gray-600 text-xs space-y-1">
          <p>1. 下载安装 moomoo（境外版）或富途牛牛</p>
          <p>2. 登录后进入：设置 → API → 开启 OpenD</p>
          <p>3. 点击「检测连接」确认 127.0.0.1:11111 可达</p>
        </div>
      )}

      {/* ── Phone verification panel — shown when OpenD needs re-auth ── */}
      {(needsVerify || verifyStep !== "idle" || verifyMsg) && (
        <div className="mt-3 border border-yellow-500/30 rounded bg-yellow-500/5 p-3 space-y-2">
          <p className="text-yellow-400 text-xs font-medium">手机验证码 — 若 OpenD 提示需要重新认证，在此操作</p>

          {verifyStep === "idle" || verifyStep === "requesting" ? (
            <button
              onClick={requestCode}
              disabled={verifyStep === "requesting"}
              className="text-xs px-3 py-1.5 rounded bg-yellow-500/20 border border-yellow-500/40 text-yellow-300 hover:bg-yellow-500/30 disabled:opacity-50 transition-colors"
            >
              {verifyStep === "requesting" ? "发送中…" : "发送手机验证码"}
            </button>
          ) : null}

          {(verifyStep === "code_sent" || verifyStep === "submitting" || verifyStep === "done") && (
            <div className="flex gap-2 items-center">
              <input
                type="text"
                value={verifyCode}
                onChange={(e) => setVerifyCode(e.target.value)}
                placeholder="输入 6 位验证码"
                maxLength={8}
                disabled={verifyStep === "submitting" || verifyStep === "done"}
                className="text-xs px-2 py-1.5 rounded bg-background border border-border text-white w-32 disabled:opacity-50 focus:outline-none focus:border-accent"
              />
              <button
                onClick={submitCode}
                disabled={verifyStep === "submitting" || verifyStep === "done" || !verifyCode.trim()}
                className="text-xs px-3 py-1.5 rounded bg-accent/20 border border-accent/40 text-accent hover:bg-accent/30 disabled:opacity-50 transition-colors"
              >
                {verifyStep === "submitting" ? "验证中…" : "提交验证码"}
              </button>
              {verifyStep !== "done" && (
                <button
                  onClick={requestCode}
                  disabled={verifyStep === "submitting"}
                  className="text-xs text-gray-500 hover:text-gray-300 disabled:opacity-50 transition-colors"
                >
                  重新发送
                </button>
              )}
            </div>
          )}

          {verifyMsg && (
            <p className={`text-xs ${verifyMsg.success ? "text-buy" : "text-red-400"}`}>
              {verifyMsg.text}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ── TickFlow market-data API key panel ──────────────────────────────────────────
function TickflowPanel() {
  const [hasKey, setHasKey] = useState(false)
  const [masked, setMasked] = useState<string | undefined>(undefined)
  const [keyInput, setKeyInput] = useState("")
  const [showKey, setShowKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [checking, setChecking] = useState(false)
  const [status, setStatus] = useState<{
    connected: boolean; latency_ms?: number; universe_count?: number; error?: string
  } | null>(null)

  useEffect(() => {
    api.getTickflowKey().then((r) => { setHasKey(r.has_key); setMasked(r.masked) }).catch(() => {})
  }, [])

  const save = async () => {
    if (!keyInput.trim()) return
    setSaving(true); setStatus(null)
    try {
      const r = await api.saveTickflowKey(keyInput.trim())
      setHasKey(r.has_key); setMasked(r.masked); setKeyInput(""); setShowKey(false)
    } catch {
      setStatus({ connected: false, error: "保存失败，请检查后端" })
    } finally { setSaving(false) }
  }

  const check = async () => {
    setChecking(true)
    try { setStatus(await api.getTickflowStatus()) }
    catch { setStatus({ connected: false, error: "无法连接到后端" }) }
    finally { setChecking(false) }
  }

  return (
    <div className="mt-8 bg-surface border border-border rounded-lg p-4 text-sm">
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-white font-medium">TickFlow（A股行情数据源）</span>
          <span className="ml-2 text-gray-500 text-xs">
            在 tickflow.org 注册并申请 API Key（免费）
          </span>
        </div>
        {hasKey && (
          <span className="text-xs text-buy">✓ 已配置{masked ? `（${masked}）` : ""}</span>
        )}
      </div>

      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={showKey ? "text" : "password"}
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            placeholder={hasKey ? "输入新 Key 可覆盖（留空保持不变）" : "tk_..."}
            className="w-full bg-bg border border-border rounded px-3 py-1.5 pr-14 text-xs text-white font-mono focus:border-accent outline-none"
          />
          {keyInput && (
            <button
              type="button"
              onClick={() => setShowKey((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500 hover:text-gray-300"
            >
              {showKey ? "隐藏" : "显示"}
            </button>
          )}
        </div>
        <button
          onClick={save}
          disabled={saving || !keyInput.trim()}
          className="text-xs px-3 py-1.5 rounded border border-border text-gray-300 hover:border-accent hover:text-accent disabled:opacity-40 transition-colors whitespace-nowrap"
        >
          {saving ? "保存中…" : "保存"}
        </button>
        <button
          onClick={check}
          disabled={checking || !hasKey}
          className="text-xs px-3 py-1.5 rounded border border-border text-gray-400 hover:border-accent hover:text-accent disabled:opacity-40 transition-colors whitespace-nowrap"
        >
          {checking ? "检测中…" : "测试连通性"}
        </button>
      </div>

      {status && (
        <div className={`mt-3 rounded p-2.5 text-xs ${
          status.connected
            ? "bg-buy/10 border border-buy/30 text-buy"
            : "bg-red-500/10 border border-red-500/30 text-red-400"
        }`}>
          {status.connected
            ? `✓ 连接成功${status.latency_ms != null ? `（${status.latency_ms}ms` : ""}${
                status.universe_count != null ? `，${status.universe_count} 个标的池）` : status.latency_ms != null ? "）" : ""
              }${status.error ? ` — ${status.error}` : ""}`
            : `✗ ${status.error ?? "连接失败"}`}
        </div>
      )}
      {!status && !hasKey && (
        <p className="mt-2 text-gray-600 text-xs">保存 API Key 后即可测试连通性</p>
      )}
    </div>
  )
}

// ── LiveModelPicker modal ─────────────────────────────────────────────────────
type LiveModel = { id: string; free_tier: boolean }

function LiveModelPicker({
  onSelect,
  onClose,
}: {
  onSelect: (id: string) => void
  onClose: () => void
}) {
  const [models, setModels] = useState<LiveModel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")

  useEffect(() => {
    api.getLiveModels()
      .then((r) => setModels(r.models))
      .catch((e) => setError(e?.response?.data?.detail ?? "获取失败"))
      .finally(() => setLoading(false))
  }, [])

  const filtered = query.trim()
    ? models.filter((m) => m.id.toLowerCase().includes(query.trim().toLowerCase()))
    : models

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-border rounded-xl w-full max-w-md shadow-2xl flex flex-col" style={{ maxHeight: "80vh" }}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div>
            <h3 className="text-sm font-semibold text-white">选择模型</h3>
            {!loading && !error && (
              <p className="text-xs text-gray-500 mt-0.5">
                共 {models.length} 个文本模型
                <span className="ml-2 text-yellow-500/80">★ 含免费额度</span>
              </p>
            )}
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white text-lg leading-none">×</button>
        </div>

        <div className="px-4 py-3 border-b border-border shrink-0">
          <input
            autoFocus
            className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-accent"
            placeholder="搜索模型名称…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {loading && <p className="text-center text-gray-500 text-sm py-8">获取中…</p>}
          {error && <p className="text-center text-red-400 text-sm py-8">{error}</p>}
          {!loading && !error && filtered.length === 0 && (
            <p className="text-center text-gray-500 text-sm py-8">无匹配结果</p>
          )}
          {!loading && !error && filtered.map((m) => (
            <button
              key={m.id}
              onClick={() => { onSelect(m.id); onClose() }}
              className="w-full flex items-center justify-between px-3 py-2 rounded hover:bg-white/5 text-left group"
            >
              <span className="text-sm text-gray-200 font-mono group-hover:text-white">{m.id}</span>
              {m.free_tier && (
                <span className="text-xs text-yellow-500/80 shrink-0 ml-2">★ 免费</span>
              )}
            </button>
          ))}
        </div>

        <div className="px-4 py-3 border-t border-border shrink-0 text-xs text-gray-600 text-center">
          实际免费用量请在
          <a href="https://bailian.console.aliyun.com" target="_blank" rel="noreferrer" className="text-accent hover:underline mx-1">百炼控制台</a>
          查看
        </div>
      </div>
    </div>
  )
}


// ── ModelInput: text input + live picker button ───────────────────────────────
function ModelInput({
  label,
  hint,
  models,
  value,
  onChange,
  loading,
  canPickLive,
}: {
  label: string
  hint: string
  models: ModelOption[]
  value: string
  onChange: (v: string) => void
  loading: boolean
  canPickLive?: boolean
}) {
  const [showPicker, setShowPicker] = useState(false)

  const knownValues = models.map((m) => m.value).filter((v) => v !== "custom")
  const dropdownValue = knownValues.includes(value) ? value : ""

  const handleDropdown = (v: string) => {
    if (v && v !== "custom") onChange(v)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-sm text-gray-400">
          {label}
          <span className="ml-1 text-gray-500 text-xs">（{hint}）</span>
        </label>
        {canPickLive && (
          <button
            type="button"
            onClick={() => setShowPicker(true)}
            className="text-xs text-accent hover:underline"
          >
            🔄 获取实时模型
          </button>
        )}
      </div>

      {/* Quick-select dropdown from static catalog */}
      <select
        className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent disabled:opacity-50 mb-1.5"
        value={dropdownValue}
        onChange={(e) => handleDropdown(e.target.value)}
        disabled={loading}
      >
        <option value="">— 从预设列表选择 —</option>
        {loading
          ? <option disabled>加载中…</option>
          : models.filter((m) => m.value !== "custom").map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))
        }
      </select>

      {/* Free-text input — single source of truth */}
      <input
        type="text"
        className="w-full bg-bg border border-border rounded-md px-3 py-1.5 text-white text-sm focus:outline-none focus:border-accent placeholder-gray-600"
        placeholder="或手动输入模型 ID，例如 qwen-plus"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />

      {showPicker && (
        <LiveModelPicker
          onSelect={onChange}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  )
}

// ── Model Pricing import panel ────────────────────────────────────────────────
type PricingRow = {
  model_id: string
  region: string
  tiers: { max_k: number | null; input_price: number; output_price: number }[]
  updated_at: string | null
}

function PricingPanel() {
  const [rows, setRows] = useState<PricingRow[]>([])
  const [loading, setLoading] = useState(false)
  const [md, setMd] = useState("")
  const [importing, setImporting] = useState(false)
  const [recalcing, setRecalcing] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [expanded, setExpanded] = useState(false)

  const loadPricing = useCallback(async () => {
    setLoading(true)
    try { setRows(await api.listPricing()) }
    catch { /* non-critical */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { loadPricing() }, [loadPricing])

  const handleImport = async () => {
    if (!md.trim()) return
    setImporting(true)
    setMsg(null)
    try {
      const r = await api.importPricingMd(md.trim())
      setMsg({ ok: true, text: `✓ 已导入 ${r.imported} 个模型（跳过 ${r.skipped} 个）：${r.models.join(", ")}` })
      setMd("")
      await loadPricing()
    } catch (e: any) {
      setMsg({ ok: false, text: e?.response?.data?.detail ?? "导入失败" })
    } finally {
      setImporting(false)
    }
  }

  const handleRecalc = async () => {
    setRecalcing(true)
    setMsg(null)
    try {
      const r = await api.recalculateCosts()
      const delta = r.total_cost_delta >= 0 ? `+¥${r.total_cost_delta.toFixed(4)}` : `-¥${Math.abs(r.total_cost_delta).toFixed(4)}`
      setMsg({ ok: true, text: `✓ 已重算 ${r.updated} 份报告成本（跳过 ${r.skipped} 份），总差额 ${delta}` })
    } catch (e: any) {
      setMsg({ ok: false, text: e?.response?.data?.detail ?? "重算失败" })
    } finally {
      setRecalcing(false)
    }
  }

  const handleDelete = async (modelId: string) => {
    try {
      await api.deletePricing(modelId)
      setRows((prev) => prev.filter((r) => r.model_id !== modelId))
    } catch { /* ignore */ }
  }

  return (
    <div className="mt-8 bg-surface border border-border rounded-lg p-4 text-sm">
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-white font-medium">模型计费价格表</span>
          <span className="ml-2 text-gray-500 text-xs">
            从阿里百炼价格页面复制 Markdown 导入，支持阶梯计费精算
          </span>
        </div>
        <div className="flex gap-2">
          {rows.length > 0 && (
            <button
              onClick={handleRecalc}
              disabled={recalcing}
              className="text-xs px-3 py-1 rounded border border-border text-gray-400 hover:border-accent hover:text-accent disabled:opacity-50 transition-colors"
            >
              {recalcing ? "重算中…" : "重算历史报告成本"}
            </button>
          )}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs px-3 py-1 rounded border border-border text-gray-400 hover:border-accent hover:text-accent transition-colors"
          >
            {expanded ? "收起" : "导入价格表"}
          </button>
        </div>
      </div>

      {/* Import section */}
      {expanded && (
        <div className="mb-4 space-y-2">
          <p className="text-xs text-gray-500">
            打开{" "}
            <span className="text-accent">阿里云百炼 → 帮助文档 → 模型价格表</span>，
            选中"## 中国内地"区域的全部 Markdown 内容复制粘贴到下方：
          </p>
          <textarea
            className="w-full h-40 bg-bg border border-border rounded-md px-3 py-2 text-xs text-gray-300 font-mono focus:outline-none focus:border-accent resize-y"
            placeholder={"## 中国内地\n\n| 模型 ID | 模式 | 单次请求的输入Token数 | 输入单价 | 输出单价 | 免费额度 |\n| --- | --- | --- | --- | --- | --- |\n| qwen-plus | 非思考 | 0<Token≤1M | 0.8元 | 2元 | ... |"}
            value={md}
            onChange={(e) => setMd(e.target.value)}
          />
          <button
            onClick={handleImport}
            disabled={importing || !md.trim()}
            className="px-4 py-1.5 rounded bg-accent text-black text-xs font-bold hover:bg-accent/80 disabled:opacity-50 transition-colors"
          >
            {importing ? "导入中…" : "解析并保存"}
          </button>
        </div>
      )}

      {msg && (
        <div className={`text-xs rounded px-3 py-2 mb-3 ${msg.ok ? "bg-buy/10 text-buy border border-buy/30" : "bg-red-500/10 text-red-400 border border-red-500/30"}`}>
          {msg.text}
        </div>
      )}

      {/* Loaded models table */}
      {loading ? (
        <p className="text-gray-600 text-xs">加载中…</p>
      ) : rows.length === 0 ? (
        <p className="text-gray-600 text-xs">暂无价格数据，请从阿里百炼导入</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-gray-400">
            <thead>
              <tr className="border-b border-border text-gray-500 text-left">
                <th className="pb-1.5 pr-4 font-medium">模型</th>
                <th className="pb-1.5 pr-4 font-medium">阶梯</th>
                <th className="pb-1.5 pr-4 font-medium">输入价 /百万</th>
                <th className="pb-1.5 pr-4 font-medium">输出价 /百万</th>
                <th className="pb-1.5 font-medium">更新时间</th>
                <th className="pb-1.5"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) =>
                row.tiers.map((tier, ti) => (
                  <tr key={`${row.model_id}-${ti}`} className="border-b border-border/30">
                    {ti === 0 && (
                      <td className="py-1.5 pr-4 font-mono text-gray-300 align-top" rowSpan={row.tiers.length}>
                        {row.model_id}
                      </td>
                    )}
                    <td className="py-1.5 pr-4 text-gray-500">
                      {tier.max_k == null ? "无上限" : `≤${tier.max_k}K`}
                    </td>
                    <td className="py-1.5 pr-4">¥{tier.input_price}</td>
                    <td className="py-1.5 pr-4">¥{tier.output_price}</td>
                    {ti === 0 && (
                      <>
                        <td className="py-1.5 text-gray-600 align-top" rowSpan={row.tiers.length}>
                          {row.updated_at ? row.updated_at.slice(0, 10) : "—"}
                        </td>
                        <td className="py-1.5 align-top" rowSpan={row.tiers.length}>
                          <button
                            onClick={() => handleDelete(row.model_id)}
                            className="text-gray-600 hover:text-red-400 transition-colors"
                            title="删除"
                          >
                            ✕
                          </button>
                        </td>
                      </>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}


// ── Main Settings page ────────────────────────────────────────────────────────
export default function SettingsPage() {
  const [saved, setSaved] = useState<Settings | null>(null)
  const [providers, setProviders] = useState<Provider[]>([])
  const [quickModels, setQuickModels] = useState<ModelOption[]>([])
  const [deepModels, setDeepModels] = useState<ModelOption[]>([])

  const [provider, setProvider] = useState("qwen-cn")
  const [apiKey, setApiKey] = useState("")
  const [deepModel, setDeepModel] = useState("")
  const [quickModel, setQuickModel] = useState("")
  const [backendUrl, setBackendUrl] = useState("")
  const [maxApiCalls, setMaxApiCalls] = useState(60)
  const [inputCostPerMillion, setInputCostPerMillion] = useState(0.0)
  const [outputCostPerMillion, setOutputCostPerMillion] = useState(0.0)
  const [showKey, setShowKey] = useState(false)

  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [loadingModels, setLoadingModels] = useState(false)

  const loadModels = useCallback(async (p: string, keepCurrent = false) => {
    setLoadingModels(true)
    try {
      const data = await api.getModels(p)
      setQuickModels(data.quick)
      setDeepModels(data.deep)
      if (!keepCurrent) {
        setQuickModel(data.quick.find((m) => m.value !== "custom")?.value ?? "")
        setDeepModel(data.deep.find((m) => m.value !== "custom")?.value ?? "")
      }
    } finally {
      setLoadingModels(false)
    }
  }, [])

  useEffect(() => {
    Promise.all([api.getSettings(), api.getProviders()]).then(([s, ps]) => {
      setSaved(s)
      setProviders(ps)
      setProvider(s.provider)
      setBackendUrl(s.backend_url ?? "")
      setMaxApiCalls(s.max_api_calls ?? 60)
      setInputCostPerMillion(s.input_cost_per_million ?? 0.0)
      setOutputCostPerMillion(s.output_cost_per_million ?? 0.0)
      api.getModels(s.provider).then((data) => {
        setQuickModels(data.quick)
        setDeepModels(data.deep)
        setQuickModel(s.quick_model)
        setDeepModel(s.deep_model)
      })
    })
  }, [])

  const handleProviderChange = (p: string) => {
    setProvider(p)
    setTestResult(null)
    loadModels(p, false)
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!deepModel.trim() || !quickModel.trim()) {
      setSaveMsg({ ok: false, text: "请填写深度模型和快速模型" })
      return
    }
    setSaving(true)
    setSaveMsg(null)
    setTestResult(null)
    try {
      const payload: SettingsUpdate = {
        provider,
        deep_model: deepModel.trim(),
        quick_model: quickModel.trim(),
        backend_url: backendUrl || undefined,
        max_api_calls: maxApiCalls,
        input_cost_per_million: inputCostPerMillion,
        output_cost_per_million: outputCostPerMillion,
      }
      if (apiKey.trim()) payload.api_key = apiKey.trim()
      const updated = await api.saveSettings(payload)
      setSaved(updated)
      setApiKey("")
      setSaveMsg({ ok: true, text: "配置已保存 ✓" })
    } catch {
      setSaveMsg({ ok: false, text: "保存失败，请检查网络" })
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    setSaveMsg(null)
    try {
      const result = await api.testConnection()
      setTestResult(result)
    } catch {
      setTestResult({ success: false, error: "请求失败，请检查服务是否运行" })
    } finally {
      setTesting(false)
    }
  }

  const currentProvider = providers.find((p) => p.value === provider)

  return (
    <div className="max-w-xl mx-auto px-6 py-10">
      <h1 className="text-2xl font-bold text-white mb-2">API 配置</h1>
      <p className="text-gray-400 text-sm mb-8">
        配置 LLM 提供商、模型和 API Key。下拉列表快速选择，也可直接手动输入模型 ID。
      </p>

      <form onSubmit={handleSave} className="space-y-5">

        {/* Provider */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">LLM 提供商</label>
          <select
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            value={provider}
            onChange={(e) => handleProviderChange(e.target.value)}
          >
            {providers.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>

        {/* API Key */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            {currentProvider?.api_key_label ?? "API Key"}
            {saved?.has_api_key && (
              <span className="ml-2 text-xs text-buy">✓ 已配置</span>
            )}
          </label>
          <div className="relative">
            <input
              type={showKey ? "text" : "password"}
              className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent pr-16"
              placeholder={saved?.has_api_key ? "留空则保留现有 Key" : "粘贴你的 API Key"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <button
              type="button"
              onClick={() => setShowKey((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-white px-2 py-1"
            >
              {showKey ? "隐藏" : "显示"}
            </button>
          </div>
        </div>

        {/* Deep Model */}
        <ModelInput
          label="深度模型"
          hint="研究员 · 辩论 · 风控"
          models={deepModels}
          value={deepModel}
          onChange={setDeepModel}
          loading={loadingModels}
          canPickLive={saved?.has_api_key && (provider === "qwen-cn" || provider === "qwen")}
        />

        {/* Quick Model */}
        <ModelInput
          label="快速模型"
          hint="分析师 · 工具调用"
          models={quickModels}
          value={quickModel}
          onChange={setQuickModel}
          loading={loadingModels}
          canPickLive={saved?.has_api_key && (provider === "qwen-cn" || provider === "qwen")}
        />

        {/* Backend URL */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            自定义 API 地址
            <span className="ml-1 text-gray-500 text-xs">（可选，用于代理或私有部署）</span>
          </label>
          <input
            type="text"
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            placeholder="例如：https://api.openai-proxy.com/v1"
            value={backendUrl}
            onChange={(e) => setBackendUrl(e.target.value)}
          />
        </div>

        {/* API call limit */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            单次分析 API 调用上限
            <span className="ml-1 text-gray-500 text-xs">（防止异常时反复调用，建议 60–120，depth=1 正常约 20–30 次）</span>
          </label>
          <input
            type="number"
            min={10}
            max={1000}
            step={10}
            className="w-32 bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            value={maxApiCalls}
            onChange={(e) => setMaxApiCalls(Math.max(10, Math.min(1000, Number(e.target.value) || 60)))}
          />
        </div>

        {/* Token cost per million */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            每百万 Token 成本（CNY）
            <span className="ml-1 text-gray-500 text-xs">（用于估算费用，留 0 则不显示费用）</span>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-0.5">输入成本</label>
              <input
                type="number"
                min={0}
                step={0.001}
                className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
                placeholder="例如：0.004"
                value={inputCostPerMillion || ""}
                onChange={(e) => setInputCostPerMillion(Number(e.target.value) || 0)}
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-0.5">输出成本</label>
              <input
                type="number"
                min={0}
                step={0.001}
                className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
                placeholder="例如：0.016"
                value={outputCostPerMillion || ""}
                onChange={(e) => setOutputCostPerMillion(Number(e.target.value) || 0)}
              />
            </div>
          </div>
          <p className="text-xs text-gray-600 mt-1">
            示例：百炼 qwen3.6-plus 输入 ¥0.004/千 Token = ¥4/百万，输出 ¥0.016/千 Token = ¥16/百万
          </p>
        </div>

        {saveMsg && (
          <p className={`text-sm ${saveMsg.ok ? "text-buy" : "text-red-400"}`}>
            {saveMsg.text}
          </p>
        )}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={saving}
            className="flex-1 bg-accent text-black font-bold py-2.5 rounded-md hover:bg-accent/80 disabled:opacity-50 transition-colors"
          >
            {saving ? "保存中…" : "保存配置"}
          </button>
          <button
            type="button"
            onClick={handleTest}
            disabled={testing || !saved?.has_api_key}
            title={!saved?.has_api_key ? "请先配置并保存 API Key" : ""}
            className="px-5 py-2.5 rounded-md border border-border text-gray-300 hover:border-accent hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
          >
            {testing ? "测试中…" : "连通测试"}
          </button>
        </div>
      </form>

      {/* Test result */}
      {testResult && (
        <div className={`mt-4 rounded-lg border p-4 text-sm ${
          testResult.success
            ? "border-buy/40 bg-buy/5"
            : "border-red-500/40 bg-red-500/5"
        }`}>
          {testResult.success ? (
            <div className="space-y-1">
              <div className="text-buy font-semibold">✓ 连接成功</div>
              <div className="text-gray-400">
                <span className="text-gray-500">延迟：</span>
                <span className="text-white">{testResult.latency_ms} ms</span>
                <span className="mx-2 text-gray-600">|</span>
                <span className="text-gray-500">模型：</span>
                <span className="text-white">{testResult.model}</span>
              </div>
              {testResult.response_preview && (
                <div className="text-gray-400 text-xs mt-1">
                  <span className="text-gray-500">响应：</span>
                  <span className="text-gray-300">{testResult.response_preview}</span>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-1">
              <div className="text-red-400 font-semibold">✗ 连接失败</div>
              <div className="text-gray-400 text-xs break-all">{testResult.error}</div>
            </div>
          )}
        </div>
      )}

      {/* JoinQuant status panel */}
      <JQPanel />

      {/* Futu OpenD status panel */}
      <FutuPanel />

      {/* TickFlow market-data API key panel */}
      <TickflowPanel />

      {/* Model pricing import panel */}
      <PricingPanel />

      {/* Current config summary */}
      {saved && (
        <div className="mt-8 bg-surface border border-border rounded-lg p-4 text-sm">
          <div className="text-gray-500 text-xs mb-3 uppercase tracking-wide">当前生效配置</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-gray-300">
            <span className="text-gray-500">提供商</span>
            <span>{providers.find((p) => p.value === saved.provider)?.label ?? saved.provider}</span>
            <span className="text-gray-500">深度模型</span>
            <span className="font-mono text-xs">{saved.deep_model}</span>
            <span className="text-gray-500">快速模型</span>
            <span className="font-mono text-xs">{saved.quick_model}</span>
            <span className="text-gray-500">API Key</span>
            <span className={saved.has_api_key ? "text-buy" : "text-hold"}>
              {saved.has_api_key ? "✓ 已配置" : "⚠ 未配置"}
            </span>
            <span className="text-gray-500">调用上限</span>
            <span>{saved.max_api_calls ?? 60} 次/分析</span>
            {(saved.input_cost_per_million > 0 || saved.output_cost_per_million > 0) && (
              <>
                <span className="text-gray-500">输入成本</span>
                <span className="font-mono text-xs">¥{saved.input_cost_per_million}/百万 Token</span>
                <span className="text-gray-500">输出成本</span>
                <span className="font-mono text-xs">¥{saved.output_cost_per_million}/百万 Token</span>
              </>
            )}
            {saved.backend_url && (
              <>
                <span className="text-gray-500">代理地址</span>
                <span className="truncate text-xs">{saved.backend_url}</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
