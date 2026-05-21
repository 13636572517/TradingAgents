// web/src/pages/Settings.tsx
import { useEffect, useState } from "react"
import { api } from "../api/client"
import type { Settings, SettingsUpdate } from "../types"

// ── Provider catalog ──────────────────────────────────────────────────────────
const PROVIDERS: Record<string, {
  label: string
  apiKeyLabel: string
  deepModels: [string, string][]
  quickModels: [string, string][]
}> = {
  "qwen-cn": {
    label: "阿里 通义千问（国内）",
    apiKeyLabel: "DashScope API Key（国内账号）",
    deepModels: [
      ["qwen3.6-plus", "Qwen3.6 Plus — 旗舰多模态"],
      ["qwen3.5-plus", "Qwen3.5 Plus"],
      ["qwen3-max",    "Qwen3 Max — Agent 专项"],
    ],
    quickModels: [
      ["qwen3.6-flash", "Qwen3.6 Flash — 快速版"],
      ["qwen3.5-flash", "Qwen3.5 Flash"],
    ],
  },
  "qwen": {
    label: "阿里 通义千问（国际）",
    apiKeyLabel: "DashScope API Key（国际账号）",
    deepModels: [
      ["qwen3.6-plus", "Qwen3.6 Plus"],
      ["qwen3.5-plus", "Qwen3.5 Plus"],
      ["qwen3-max",    "Qwen3 Max"],
    ],
    quickModels: [
      ["qwen3.6-flash", "Qwen3.6 Flash"],
      ["qwen3.5-flash", "Qwen3.5 Flash"],
    ],
  },
  "openai": {
    label: "OpenAI",
    apiKeyLabel: "OpenAI API Key",
    deepModels: [
      ["gpt-4o",   "GPT-4o"],
      ["gpt-4.1",  "GPT-4.1"],
      ["o3-mini",  "o3-mini"],
    ],
    quickModels: [
      ["gpt-4o-mini",  "GPT-4o Mini"],
      ["gpt-4.1-mini", "GPT-4.1 Mini"],
    ],
  },
  "anthropic": {
    label: "Anthropic (Claude)",
    apiKeyLabel: "Anthropic API Key",
    deepModels: [
      ["claude-sonnet-4-6",         "Claude Sonnet 4.6"],
      ["claude-opus-4-7",           "Claude Opus 4.7"],
    ],
    quickModels: [
      ["claude-haiku-4-5-20251001", "Claude Haiku 4.5"],
    ],
  },
  "deepseek": {
    label: "DeepSeek",
    apiKeyLabel: "DeepSeek API Key",
    deepModels: [
      ["deepseek-chat",    "DeepSeek Chat"],
      ["deepseek-reasoner","DeepSeek Reasoner"],
    ],
    quickModels: [
      ["deepseek-chat", "DeepSeek Chat"],
    ],
  },
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [provider, setProvider] = useState("qwen-cn")
  const [apiKey, setApiKey] = useState("")
  const [deepModel, setDeepModel] = useState("")
  const [quickModel, setQuickModel] = useState("")
  const [backendUrl, setBackendUrl] = useState("")
  const [showKey, setShowKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    api.getSettings().then((s) => {
      setSettings(s)
      setProvider(s.provider)
      setDeepModel(s.deep_model)
      setQuickModel(s.quick_model)
      setBackendUrl(s.backend_url ?? "")
    })
  }, [])

  // When provider changes, reset models to first option of new provider
  const handleProviderChange = (p: string) => {
    setProvider(p)
    const catalog = PROVIDERS[p]
    if (catalog) {
      setDeepModel(catalog.deepModels[0][0])
      setQuickModel(catalog.quickModels[0][0])
    }
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMsg(null)
    try {
      const payload: SettingsUpdate = {
        provider,
        deep_model: deepModel,
        quick_model: quickModel,
        backend_url: backendUrl || undefined,
      }
      if (apiKey.trim()) payload.api_key = apiKey.trim()
      const updated = await api.saveSettings(payload)
      setSettings(updated)
      setApiKey("")   // clear after save — never redisplay key
      setMsg({ ok: true, text: "配置已保存，下次提交分析时生效" })
    } catch {
      setMsg({ ok: false, text: "保存失败，请检查网络" })
    } finally {
      setSaving(false)
    }
  }

  const catalog = PROVIDERS[provider]

  return (
    <div className="max-w-lg mx-auto px-6 py-10">
      <h1 className="text-2xl font-bold text-white mb-2">API 配置</h1>
      <p className="text-gray-400 text-sm mb-8">
        配置 LLM 提供商和模型。API Key 加密存储在本地数据库中，不会上传到任何服务器。
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
            {Object.entries(PROVIDERS).map(([key, p]) => (
              <option key={key} value={key}>{p.label}</option>
            ))}
          </select>
        </div>

        {/* API Key */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            {catalog?.apiKeyLabel ?? "API Key"}
            {settings?.has_api_key && (
              <span className="ml-2 text-xs text-buy">✓ 已配置</span>
            )}
          </label>
          <div className="relative">
            <input
              type={showKey ? "text" : "password"}
              className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent pr-16"
              placeholder={settings?.has_api_key ? "留空则保留现有 Key" : "粘贴你的 API Key"}
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
          <label className="block text-sm text-gray-400 mb-1">深度分析模型（研究员 / 辩论）</label>
          <select
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            value={deepModel}
            onChange={(e) => setDeepModel(e.target.value)}
          >
            {(catalog?.deepModels ?? []).map(([id, label]) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>
        </div>

        {/* Quick Model */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">快速模型（分析师 / 工具调用）</label>
          <select
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            value={quickModel}
            onChange={(e) => setQuickModel(e.target.value)}
          >
            {(catalog?.quickModels ?? []).map(([id, label]) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>
        </div>

        {/* Backend URL (optional) */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            自定义 API 地址（可选，用于代理或私有部署）
          </label>
          <input
            type="url"
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            placeholder="例如：https://api.openai-proxy.com/v1"
            value={backendUrl}
            onChange={(e) => setBackendUrl(e.target.value)}
          />
        </div>

        {/* Message */}
        {msg && (
          <p className={`text-sm ${msg.ok ? "text-buy" : "text-red-400"}`}>
            {msg.text}
          </p>
        )}

        <button
          type="submit"
          disabled={saving}
          className="w-full bg-accent text-black font-bold py-2.5 rounded-md hover:bg-accent/80 disabled:opacity-50 transition-colors"
        >
          {saving ? "保存中…" : "保存配置"}
        </button>
      </form>

      {/* Current config summary */}
      {settings && (
        <div className="mt-8 bg-surface border border-border rounded-lg p-4 text-sm">
          <div className="text-gray-400 text-xs mb-2 uppercase tracking-wide">当前生效配置</div>
          <div className="space-y-1 text-gray-300">
            <div><span className="text-gray-500">提供商：</span>{PROVIDERS[settings.provider]?.label ?? settings.provider}</div>
            <div><span className="text-gray-500">深度模型：</span>{settings.deep_model}</div>
            <div><span className="text-gray-500">快速模型：</span>{settings.quick_model}</div>
            <div><span className="text-gray-500">API Key：</span>{settings.has_api_key ? "✓ 已配置" : "⚠ 未配置"}</div>
            {settings.backend_url && (
              <div><span className="text-gray-500">代理地址：</span>{settings.backend_url}</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
