// web/src/types.ts
export interface Analysis {
  id: string
  ticker: string
  ticker_name: string | null
  trade_date: string
  analysts: string[]
  depth: number
  status: "pending" | "running" | "complete" | "failed" | "stopped"
  stage: string
  stage_detail: string | null
  usage: UsageStats | null
  result: AnalysisResult | null
  decision: "BUY" | "HOLD" | "SELL" | null
  error: string | null
  created_at: string
  completed_at: string | null
  seen: boolean
}

export interface AnalysisResult {
  market_report: string | null
  sentiment_report: string | null
  news_report: string | null
  fundamentals_report: string | null
  investment_plan: string | null
  trader_investment_plan: string | null
  final_trade_decision: string | null
}

export interface AnalysisListResponse {
  items: Analysis[]
  total: number
}

export interface ProgressEvent {
  stage: string
  label: string
  detail?: string
  progress: number
  status: string
  decision?: string
  error?: string
}

export interface Settings {
  provider: string
  deep_model: string
  quick_model: string
  backend_url: string | null
  has_api_key: boolean
  max_api_calls: number
}

export interface SettingsUpdate {
  provider: string
  api_key?: string
  deep_model: string
  quick_model: string
  backend_url?: string
  max_api_calls: number
}

export interface ModelOption {
  label: string
  value: string
}

export interface ModelsResponse {
  quick: ModelOption[]
  deep: ModelOption[]
}

export interface Provider {
  value: string
  label: string
  api_key_label: string
}

export interface UsageSlot {
  model: string
  calls: number
  tokens_in: number
  tokens_out: number
  tool_calls: number
  cost_cny: number
}

export interface UsageStats {
  quick: UsageSlot
  deep: UsageSlot
  total_cost_cny: number
}

export interface AggregateStats {
  total_analyses: number
  completed_analyses: number
  quick: UsageSlot
  deep: UsageSlot
  total_cost_cny: number
  by_date: Record<string, { cost_cny: number; analyses: number }>
}

export interface TestResult {
  success: boolean
  latency_ms?: number
  model?: string
  provider?: string
  response_preview?: string
  error?: string
}

export interface KLineBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface KLineResponse {
  ticker: string
  range: string
  data: KLineBar[]
  error: string | null
}

export interface AuthToken {
  access_token: string
  token_type: string
}

export interface AuthUser {
  id: number
  username: string
  is_active: boolean
  is_admin: boolean
}

export interface ShareUser {
  id: number
  username: string
}

export interface AdminUser {
  id: number
  username: string
  is_active: boolean
  is_admin: boolean
  created_at: string
}
