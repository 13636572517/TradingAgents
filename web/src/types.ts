// web/src/types.ts
export interface Analysis {
  id: string
  ticker: string
  ticker_name: string | null
  trade_date: string
  analysts: string[]
  depth: number
  status: "pending" | "running" | "complete" | "failed"
  stage: string
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
}

export interface SettingsUpdate {
  provider: string
  api_key?: string
  deep_model: string
  quick_model: string
  backend_url?: string
}
