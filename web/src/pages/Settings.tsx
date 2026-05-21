// web/src/pages/Settings.tsx
import { useEffect, useState, useCallback } from "react"
import { api } from "../api/client"
import type { Settings, SettingsUpdate, ModelOption, Provider, TestResult } from "../types"

export default function SettingsPage() {
  // ── Remote data ──────────────────────────────────────────────────────────
  const [saved, setSaved] = useState<Settings | null>(null)
  const [providers, setProviders] = useState<Provider[]>([])
  const [quickModels, setQuickModels] = useState<ModelOption[]>([])
  const [deepModels, setDeepModels] = useState<ModelOption[]>([])

  // ── Form state ───────────────────────────────────────────────────────────
  const [provider, setProvider] = useState("qwen-cn")
  const [apiKey, setApiKey] = useState("")
  const [deepModel, setDeepModel] = useState("")
  const [quickModel, setQuickModel] = useState("")
  const [backendUrl, setBackendUrl] = useState("")
  const [showKey, setShowKey] = useState(false)

  // ── UI state ─────────────────────────────────────────────────────────────
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [loadingModels, setLoadingModels] = useState(false)

  // ── Load models for selected provider ────────────────────────────────────
  const loadModels = useCallback(async (p: string, keepCurrent = false) => {
    setLoadingModels(true)
    try {
      const data = await api.getModels(p)
      setQuickModels(data.quick)
      setDeepModels(data.deep)
      if (!keepCurrent) {
        setQuickModel(data.quick[0]?.value ?? "")
        setDeepModel(data.deep[0]?.value ?? "")
      }
    } finally {
      setLoadingModels(false)
    }
  }, [])

  // ── Initial load ─────────────────────────────────────────────────────────
  useEffect(() => {
    Promise.all([api.getSettings(), api.getProviders()]).then(([s, ps]) => {
      setSaved(s)
      setProviders(ps)
      setProvider(s.provider)
      setBackendUrl(s.backend_url ?? "")
      // Load models and keep current saved selection
      api.getModels(s.provider).then((data) => {
        setQuickModels(data.quick)
        setDeepModels(data.deep)
        setQuickModel(s.quick_model)
        setDeepModel(s.deep_model)
      })
    })
  }, [])

  // ── Provider change → reload model lists ─────────────────────────────────
  const handleProviderChange = (p: string) => {
    setProvider(p)
    setTestResult(null)
    loadModels(p, false)
  }

  // ── Save ─────────────────────────────────────────────────────────────────
  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setSaveMsg(null)
    setTestResult(null)
    try {
      const payload: SettingsUpdate = {
        provider,
        deep_model: deepModel,
        quick_model: quickModel,
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

  // ── Test connection ───────────────────────────────────────────────────────
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
        配置 LLM 提供商、模型和 API Key。保存后下次提交分析即生效。
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
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            深度模型
            <span className="ml-1 text-gray-500 text-xs">（研究员 · 辩论 · 风控）</span>
          </label>
          <select
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent disabled:opacity-50"
            value={deepModel}
            onChange={(e) => setDeepModel(e.target.value)}
            disabled={loadingModels}
          >
            {loadingModels
              ? <option>加载中…</option>
              : deepModels.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))
            }
          </select>
          {deepModel === "custom" && (
            <input
              className="mt-2 w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent text-sm"
              placeholder="输入自定义模型 ID"
              value={deepModel === "custom" ? "" : deepModel}
              onChange={(e) => setDeepModel(e.target.value)}
            />
          )}
        </div>

        {/* Quick Model */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            快速模型
            <span className="ml-1 text-gray-500 text-xs">（分析师 · 工具调用）</span>
          </label>
          <select
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent disabled:opacity-50"
            value={quickModel}
            onChange={(e) => setQuickModel(e.target.value)}
            disabled={loadingModels}
          >
            {loadingModels
              ? <option>加载中…</option>
              : quickModels.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))
            }
          </select>
          {quickModel === "custom" && (
            <input
              className="mt-2 w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent text-sm"
              placeholder="输入自定义模型 ID"
              value={quickModel === "custom" ? "" : quickModel}
              onChange={(e) => setQuickModel(e.target.value)}
            />
          )}
        </div>

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

        {/* Save message */}
        {saveMsg && (
          <p className={`text-sm ${saveMsg.ok ? "text-buy" : "text-red-400"}`}>
            {saveMsg.text}
          </p>
        )}

        {/* Buttons */}
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
            <span>{saved.deep_model}</span>
            <span className="text-gray-500">快速模型</span>
            <span>{saved.quick_model}</span>
            <span className="text-gray-500">API Key</span>
            <span className={saved.has_api_key ? "text-buy" : "text-hold"}>
              {saved.has_api_key ? "✓ 已配置" : "⚠ 未配置"}
            </span>
            {saved.backend_url && (
              <>
                <span className="text-gray-500">代理地址</span>
                <span className="truncate">{saved.backend_url}</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
