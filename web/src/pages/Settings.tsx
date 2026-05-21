// web/src/pages/Settings.tsx
import { useEffect, useState, useCallback } from "react"
import { api } from "../api/client"
import type { Settings, SettingsUpdate, ModelOption, Provider, TestResult } from "../types"

// ── ModelInput: dropdown quick-select + free-text input (always editable) ────
function ModelInput({
  label,
  hint,
  models,
  value,
  onChange,
  loading,
}: {
  label: string
  hint: string
  models: ModelOption[]
  value: string
  onChange: (v: string) => void
  loading: boolean
}) {
  // Which dropdown option is currently selected (empty string = none / custom)
  const knownValues = models.map((m) => m.value).filter((v) => v !== "custom")
  const dropdownValue = knownValues.includes(value) ? value : ""

  const handleDropdown = (v: string) => {
    if (v && v !== "custom") onChange(v)
  }

  return (
    <div>
      <label className="block text-sm text-gray-400 mb-1">
        {label}
        <span className="ml-1 text-gray-500 text-xs">（{hint}）</span>
      </label>

      {/* Quick-select dropdown */}
      <select
        className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent disabled:opacity-50 mb-1.5"
        value={dropdownValue}
        onChange={(e) => handleDropdown(e.target.value)}
        disabled={loading}
      >
        <option value="">— 从列表选择 —</option>
        {loading
          ? <option disabled>加载中…</option>
          : models.filter((m) => m.value !== "custom").map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))
        }
      </select>

      {/* Free-text input — always visible, single source of truth */}
      <input
        type="text"
        className="w-full bg-bg border border-border rounded-md px-3 py-1.5 text-white text-sm focus:outline-none focus:border-accent placeholder-gray-600"
        placeholder="或手动输入模型 ID，例如 qwen-plus"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
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
        />

        {/* Quick Model */}
        <ModelInput
          label="快速模型"
          hint="分析师 · 工具调用"
          models={quickModels}
          value={quickModel}
          onChange={setQuickModel}
          loading={loadingModels}
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
