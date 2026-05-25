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
            ? "✓ OpenD 已连接，美股数据将优先使用富途"
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
