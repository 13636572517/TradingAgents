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
  masked_api_key: string | null
  max_api_calls: number
  input_cost_per_million: number
  output_cost_per_million: number
}

export interface SettingsUpdate {
  provider: string
  api_key?: string
  deep_model: string
  quick_model: string
  backend_url?: string
  max_api_calls: number
  input_cost_per_million: number
  output_cost_per_million: number
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
  total_tokens: number
  total_cost_cny: number
  by_date: Record<string, { tokens: number; analyses: number; cost_cny: number }>
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

export interface Strategy {
  id: string
  analysis_id: string
  ticker: string
  ticker_name: string | null
  trade_date: string
  direction: "BUY" | "HOLD" | "SELL" | null
  entry_price: number | null
  stop_loss: number | null
  target_price: number | null
  position_size: string | null
  time_horizon: string | null
  current_price: number | null
  price_updated_at: string | null
  status: "active" | "expired" | "closed"
  extraction_method: "regex" | "ai" | null
  confidence: "high" | "medium" | "low" | null
  stop_loss_basis: string | null
  target_price_basis: string | null
  extraction_note: string | null
  created_at: string
  closed_at: string | null
}

export interface AdminUser {
  id: number
  username: string
  is_active: boolean
  is_admin: boolean
  created_at: string
}

// ── Stock Screener ──────────────────────────────────────────────────────────────

export interface ScreeningCandidate {
  id: string
  run_id: string
  board_name: string
  board_level: number       // 1 = SW1, 2 = SW2
  board_pe_pct: number | null
  board_pb_pct: number | null
  board_valuation_method: "historical" | "cross_section" | null
  code: string | null       // 6-digit A-share code
  ticker: string            // YF format e.g. 600519.SS
  ticker_name: string | null
  price: number | null
  pct_change: number | null
  total_mktcap: number | null
  pe: number | null
  pb: number | null
  roe: number | null
  amount: number | null
  net_inflow: number | null
  net_profit_yoy: number | null
  debt_ratio: number | null
  gross_margin: number | null
  ocf_to_revenue: number | null
  eps_ttm: number | null
  bps: number | null
  rank_in_board: number | null
  score: number | null
  reason: string | null
  analysis_id: string | null
  created_at: string
}

export interface BoardValuation {
  name: string
  level: number           // 1 = SW1 一级, 2 = SW2 二级
  pe: number | null
  pb: number | null
  pe_pct: number | null
  pb_pct: number | null
  is_undervalued: boolean
  valuation_method: "historical" | "cross_section" | null
  pct_change: number | null
  member_count: number | null
}

export interface UndervaluedBoard {
  name: string
  pe: number | null
  pb: number | null
  pe_pct: number | null
  pb_pct: number | null
  valuation_method: "historical" | "cross_section"
  pct_change: number | null
  member_count: number | null
}

export interface ScreeningSummary {
  boards_scanned?: number
  sw1_count?: number
  sw2_count?: number
  sw1_undervalued?: number
  sw2_undervalued?: number
  candidate_count?: number
  roe_available?: boolean
  moneyflow_available?: boolean
  undervalued_boards?: UndervaluedBoard[]
  all_boards?: BoardValuation[]
}

export interface BoardMember {
  code: string
  ticker: string
  name: string
  price: number | null
  pct_change: number | null
  amount: number | null
  pe: number | null
  pb: number | null
  roe: number | null
  total_mktcap: number | null
  net_profit_yoy: number | null
  debt_ratio: number | null
  gross_margin: number | null
  ocf_to_revenue: number | null
  eps_ttm: number | null
  bps: number | null
  is_candidate: boolean
  candidate_id: string | null
  score: number | null
  rank_in_board: number | null
  reason: string | null
  analysis_id: string | null
}

export interface BoardMembersResponse {
  run_id: string
  board_name: string
  level: number
  members: BoardMember[]
}

export interface StockDetailQuote {
  symbol: string | null
  code: string | null
  name: string | null
  last_price: number | null
  prev_close: number | null
  open: number | null
  high: number | null
  low: number | null
  volume: number | null
  amount: number | null
  change_pct: number | null
  amplitude: number | null
  turnover_rate: number | null
  total_mktcap: number | null
  float_mktcap: number | null
  pe: number | null
  pb: number | null
}

export interface StockDetailKline {
  date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
  amount: number | null
}

export interface StockDetail {
  ticker: string
  tf_code: string
  quote?: StockDetailQuote
  metrics: Record<string, unknown>[]
  balance: Record<string, unknown>[]
  income: Record<string, unknown>[]
  cashflow: Record<string, unknown>[]
  klines: StockDetailKline[]
  errors: string[]
  past_analyses: { id: string; trade_date: string; created_at: string | null; depth: number }[]
  last_screening: {
    run_id: string
    board_name: string
    board_level: number
    score: number | null
    rank_in_board: number | null
    reason: string | null
  } | null
}

export interface ScreeningRun {
  id: string
  run_date: string
  status: "running" | "complete" | "failed"
  trigger: "manual" | "scheduled"
  params: unknown | null
  summary: ScreeningSummary | null
  error: string | null
  created_at: string
  completed_at: string | null
  candidates?: ScreeningCandidate[]
}
