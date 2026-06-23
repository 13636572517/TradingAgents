// web/src/pages/Screener.tsx
import { useEffect, useState, useCallback, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api/client"
import type { ScreeningRun, BoardValuation, ScreeningCandidate, BoardMember } from "../types"
import { ALL_SW1, ALL_SW2, SW1_TO_SW2, SW2_TO_SW1 } from "../data/swIndustries"

// ── Formatters ─────────────────────────────────────────────────────────────────

function fmtNum(v: number | null | undefined, suffix = ""): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(1)}${suffix}`
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(0)}%`
}

function fmtYi(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—"
  return `${(v / 1e8).toFixed(1)}亿`
}

function fmtNum2(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—"
  return v.toFixed(2)
}

function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "text-gray-400"
  return v > 0 ? "text-red-400" : "text-green-400"
}

// ─ Board Card ────────────────────────────────────────────────────────────────

function BoardCard({
  board, candidateCount, onOpen,
}: {
  board: BoardValuation
  candidateCount: number
  onOpen: () => void
}) {
  const pctClass = board.is_undervalued
    ? "border-amber-500/50 bg-amber-950/10 hover:bg-amber-950/20"
    : "border-border bg-surface hover:bg-white/[0.02]"

  return (
    <div
      className={`rounded-lg border overflow-hidden cursor-pointer transition-colors ${pctClass}`}
      onClick={onOpen}
    >
      <div className="px-3 py-2.5">
        <div className="flex items-center justify-between mb-1.5">
          <span className="font-medium text-gray-100 text-sm truncate">{board.name}</span>
          <div className="flex items-center gap-1 shrink-0 ml-1">
            {board.is_undervalued && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40">
                低估
              </span>
            )}
            {candidateCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-accent/15 text-accent border border-accent/30">
                候选 {candidateCount}
              </span>
            )}
            <span className="text-gray-500 text-[10px]">›</span>
          </div>
        </div>
        <div className="flex items-center gap-x-3 gap-y-0.5 text-xs text-gray-500 flex-wrap">
          <span>PE {fmtNum(board.pe)}</span>
          <span>PB {fmtNum(board.pb)}</span>
          {board.pe_pct !== null && board.pb_pct !== null && (
            <>
              <span className={board.is_undervalued ? "text-buy" : ""}>
                PE分位 {fmtPct(board.pe_pct)}
              </span>
              <span className={board.is_undervalued ? "text-buy" : ""}>
                PB分位 {fmtPct(board.pb_pct)}
              </span>
            </>
          )}
          <span>{board.member_count ?? "—"} 只</span>
        </div>
      </div>
    </div>
  )
}

// ── Valuation filter rules ────────────────────────────────────────────────────
//
// Common value-investing heuristics for spotting undervalued stocks. Each rule
// is independently toggleable (checkbox); enabled rules are ANDed together.
// Rules that need data we don't currently collect per-candidate (PEG, 股息率,
// DCF 内在价值, AH 折溢价率) are intentionally omitted — see follow-up note.

// Unified row shape for the candidates table — covers both screened candidates
// (ScreeningCandidate) and plain board members fetched on-demand when "包含非候选股"
// is enabled (BoardMember, enriched with board_name/board_level/board_pe_pct/board_pb_pct).
interface CandidateRow {
  code: string | null
  ticker: string
  ticker_name: string | null
  board_name: string
  board_level: number
  board_pe_pct: number | null
  board_pb_pct: number | null
  price: number | null
  pct_change: number | null
  total_mktcap: number | null
  pe: number | null
  pb: number | null
  roe: number | null
  net_profit_yoy: number | null
  debt_ratio: number | null
  gross_margin: number | null
  ocf_to_revenue: number | null
  eps_ttm: number | null
  bps: number | null
  rank_in_board: number | null
  score: number | null
  analysis_id: string | null
  is_candidate: boolean
}

interface FilterRule {
  key: string
  label: string
  description: string
  test: (c: CandidateRow) => boolean
}

const FILTER_RULES: FilterRule[] = [
  {
    key: "pb_below_1",
    label: "PB < 1（破净）",
    description: "市净率低于1，股价低于每股净资产（账面价值），可能被低估，对重资产行业（银行、地产等）尤为有效。",
    test: (c) => c.pb != null && c.pb > 0 && c.pb < 1,
  },
  {
    key: "board_pe_low",
    label: "行业PE分位 < 30%",
    description: "所属申万板块的市盈率处于近年历史分位的30%以下，意味着当前估值比历史上70%的时间都便宜。",
    test: (c) => c.board_pe_pct != null && c.board_pe_pct < 30,
  },
  {
    key: "board_pb_low",
    label: "行业PB分位 < 30%",
    description: "所属申万板块的市净率处于近年历史分位的30%以下。",
    test: (c) => c.board_pb_pct != null && c.board_pb_pct < 30,
  },
  {
    key: "pe_reasonable",
    label: "PE ∈ (0, 30]",
    description: "市盈率为正且不超过30倍：排除亏损股（PE为负）与明显高估的股票。",
    test: (c) => c.pe != null && c.pe > 0 && c.pe <= 30,
  },
  {
    key: "roe_healthy",
    label: "ROE ≥ 8%",
    description: "净资产收益率不低于8%，确保盈利能力达标，避免低估值但基本面差的“价值陷阱”。",
    test: (c) => c.roe != null && c.roe >= 8,
  },
  {
    key: "mktcap_large",
    label: "市值 ≥ 50亿",
    description: "总市值不低于50亿元，排除流动性差、波动剧烈的小盘股，降低交易风险。",
    test: (c) => c.total_mktcap != null && c.total_mktcap >= 5e9,
  },
  {
    key: "board_leader",
    label: "板块龙头（排名前2）",
    description: "在所属申万板块的龙头评分中排名前2，代表该股在行业内具有相对优势地位（市值、流动性、ROE、资金流综合评分）。",
    test: (c) => c.rank_in_board != null && c.rank_in_board <= 2,
  },
  {
    key: "no_chasing_high",
    label: "当日涨幅 ≤ 5%",
    description: "当日涨幅不超过5%，避免追高刚大涨的股票，更符合价值投资逢低布局的思路。",
    test: (c) => c.pct_change != null && c.pct_change <= 5,
  },
  {
    key: "peg_below_1",
    label: "PEG < 1",
    description: "市盈率相对净利润增速（PEG = PE / 净利润同比增速%）低于1，意味着估值相对其盈利成长性而言被低估。仅适用于净利润正增长的公司。",
    test: (c) =>
      c.pe != null && c.pe > 0 &&
      c.net_profit_yoy != null && c.net_profit_yoy > 0 &&
      c.pe / c.net_profit_yoy < 1,
  },
  {
    key: "debt_ratio_low",
    label: "资产负债率 < 40%",
    description: "资产负债率低于40%，财务杠杆较低，偿债压力小，抗风险能力较强。",
    test: (c) => c.debt_ratio != null && c.debt_ratio < 40,
  },
  {
    key: "gross_margin_high",
    label: "毛利率 ≥ 30%",
    description: "毛利率不低于30%，反映公司产品或服务具有较强的定价权与护城河。",
    test: (c) => c.gross_margin != null && c.gross_margin >= 30,
  },
  {
    key: "ocf_positive",
    label: "经营现金流健康（OCF/营收 > 0）",
    description: "经营活动现金流占营收比例为正，说明账面利润有真实现金流入支撑，排除“纸面盈利”风险。",
    test: (c) => c.ocf_to_revenue != null && c.ocf_to_revenue > 0,
  },
  {
    key: "below_graham_number",
    label: "现价 < 格雷厄姆数",
    description: "格雷厄姆数 = √(22.5 × 每股收益TTM × 每股净资产)，是格雷厄姆提出的防御型投资者估值上限（隐含PE≤15且PB≤1.5）。现价低于该值说明股价相对盈利和净资产具有安全边际。",
    test: (c) => {
      if (c.eps_ttm == null || c.bps == null || c.price == null) return false
      if (c.eps_ttm <= 0 || c.bps <= 0) return false
      const graham = Math.sqrt(22.5 * c.eps_ttm * c.bps)
      return c.price < graham
    },
  },
]

// ── Multi-Select Dropdown ─────────────────────────────────────────────────────

function MultiSelect({
  options, selected, onChange, placeholder = "全部",
}: {
  options: string[]
  selected: Set<string>
  onChange: (s: Set<string>) => void
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)

  const toggle = (opt: string) => {
    const next = new Set(selected)
    if (next.has(opt)) next.delete(opt)
    else next.add(opt)
    onChange(next)
  }

  const selectAll = () => {
    if (selected.size === options.length) onChange(new Set())
    else onChange(new Set(options))
  }

  const display = selected.size === 0
    ? placeholder
    : selected.size === options.length
    ? "全部"
    : `${selected.size} 项`

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border transition-colors ${
          selected.size > 0
            ? "border-accent/40 bg-accent/10 text-accent"
            : "border-border bg-surface text-gray-400 hover:border-gray-500"
        }`}
      >
        <span>{display}</span>
        <span className="text-[8px]">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div
          className="absolute left-0 top-full mt-1 w-56 max-h-64 overflow-y-auto rounded-lg border border-border bg-surface shadow-xl z-50 p-2"
          onMouseDown={(e) => e.preventDefault()}
        >
          <button
            onClick={selectAll}
            className="w-full text-left text-xs px-2 py-1 rounded hover:bg-accent/10 text-gray-300"
          >
            {selected.size === options.length ? " 全部" : "☐ 全部"}
          </button>
          <div className="my-1 border-t border-border" />
          {options.map((opt) => (
            <label
              key={opt}
              className="flex items-center gap-2 text-xs px-2 py-1 rounded hover:bg-accent/10 cursor-pointer text-gray-300"
            >
              <input
                type="checkbox"
                checked={selected.has(opt)}
                onChange={() => toggle(opt)}
                className="accent-accent"
              />
              <span className="truncate">{opt}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function Screener() {
  const navigate = useNavigate()
  const [run, setRun] = useState<ScreeningRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [autoAnalyze, setAutoAnalyze] = useState(false)
  const [depth, setDepth] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<"sw1" | "sw2" | "candidates">("sw1")

  // Two-level industry filter for candidates tab (一级 -> 二级)
  const [selectedSW1, setSelectedSW1] = useState<Set<string>>(new Set())
  const [selectedSW2, setSelectedSW2] = useState<Set<string>>(new Set())

  // Include non-candidate board members in the candidates table (default off)
  const [includeNonCandidates, setIncludeNonCandidates] = useState(false)
  const [extraMembers, setExtraMembers] = useState<CandidateRow[]>([])
  const [loadingMembers, setLoadingMembers] = useState(false)

  // Valuation filter rules for candidates tab (checkbox-enabled, ANDed)
  const [activeRules, setActiveRules] = useState<Set<string>>(new Set())
  const toggleRule = (key: string) => {
    setActiveRules((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const loadLatest = useCallback(async () => {
    try {
      const r = await api.getLatestScreeningRun()
      setRun(r)
    } catch {
      setRun(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadLatest() }, [loadLatest])

  // Poll while running
  useEffect(() => {
    if (!run || run.status !== "running") return
    const id = setInterval(async () => {
      try {
        const r = await api.getScreeningRun(run.id)
        setRun(r)
      } catch { /* ignore */ }
    }, 4000)
    return () => clearInterval(id)
  }, [run])

  // Reset sector filter when tab switches to candidates
  useEffect(() => {
    if (tab === "candidates") {
      setSelectedSW1(new Set())
      setSelectedSW2(new Set())
    }
  }, [tab])

  const handleRun = async () => {
    setStarting(true)
    setError(null)
    try {
      const r = await api.runScreening({ auto_analyze: autoAnalyze, depth })
      setRun(r)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "启动筛选失败")
    } finally {
      setStarting(false)
    }
  }

  // Data
  const allBoards: BoardValuation[] = run?.summary?.all_boards ?? []
  const candidates: ScreeningCandidate[] = run?.candidates ?? []

  // Filter by tab
  const level = tab === "sw1" ? 1 : 2
  const filteredBoards = allBoards.filter((b) => b.level === level)
  const filteredCandidates = candidates.filter((c) => c.board_level === level)

  // Sort: undervalued first, then by PE+PB percentile
  const sortedBoards = [...filteredBoards].sort((a, b) => {
    if (a.is_undervalued !== b.is_undervalued) return a.is_undervalued ? -1 : 1
    return ((a.pe_pct ?? 100) + (a.pb_pct ?? 100)) - ((b.pe_pct ?? 100) + (b.pb_pct ?? 100))
  })

  // Candidates normalized into the unified row shape
  const candidateRows: CandidateRow[] = useMemo(
    () => candidates.map((c) => ({ ...c, is_candidate: true })),
    [candidates],
  )

  // SW2 options narrowed by selected SW1 (一级行业); empty/full selection = all 130
  const sw2Options = useMemo(() => {
    if (selectedSW1.size === 0 || selectedSW1.size === ALL_SW1.length) return ALL_SW2
    return Array.from(selectedSW1).flatMap((s1) => SW1_TO_SW2[s1] ?? [])
  }, [selectedSW1])

  // Prune SW2 selection when SW1 selection changes and narrows the option set
  useEffect(() => {
    setSelectedSW2((prev) => {
      if (prev.size === 0) return prev
      const next = new Set(Array.from(prev).filter((s2) => sw2Options.includes(s2)))
      return next.size === prev.size ? prev : next
    })
  }, [sw2Options])

  const sw1Active = selectedSW1.size > 0 && selectedSW1.size < ALL_SW1.length
  const sw2Active = selectedSW2.size > 0 && selectedSW2.size < sw2Options.length

  const passesSectorFilter = useCallback((row: CandidateRow) => {
    if (sw1Active) {
      const parent = row.board_level === 1 ? row.board_name : SW2_TO_SW1[row.board_name]
      if (!parent || !selectedSW1.has(parent)) return false
    }
    if (sw2Active && row.board_level === 2 && !selectedSW2.has(row.board_name)) return false
    return true
  }, [sw1Active, sw2Active, selectedSW1, selectedSW2])

  // SW2 boards in scope, used to fetch full member lists when "包含非候选股" is on
  const activeBoards = useMemo(() => {
    const seen = new Set<string>()
    const boards: { level: number; name: string }[] = []
    for (const c of candidateRows) {
      if (c.board_level !== 2 || !passesSectorFilter(c)) continue
      if (seen.has(c.board_name)) continue
      seen.add(c.board_name)
      boards.push({ level: 2, name: c.board_name })
    }
    return boards
  }, [candidateRows, passesSectorFilter])

  const MAX_NON_CANDIDATE_BOARDS = 15

  // Fetch full board member lists (non-candidates) when enabled
  useEffect(() => {
    if (!includeNonCandidates || !run || activeBoards.length === 0
        || activeBoards.length > MAX_NON_CANDIDATE_BOARDS) {
      setExtraMembers([])
      return
    }
    let cancelled = false
    setLoadingMembers(true)
    const allBoards: BoardValuation[] = run.summary?.all_boards ?? []
    Promise.all(
      activeBoards.map((b) => api.getBoardMembers(run.id, b.level, b.name).catch(() => null)),
    ).then((results) => {
      if (cancelled) return
      const extras: CandidateRow[] = []
      results.forEach((res, i) => {
        if (!res) return
        const board = activeBoards[i]
        const bv = allBoards.find((x) => x.level === board.level && x.name === board.name)
        for (const m of res.members as BoardMember[]) {
          if (m.is_candidate) continue
          extras.push({
            code: m.code,
            ticker: m.ticker,
            ticker_name: m.name,
            board_name: board.name,
            board_level: board.level,
            board_pe_pct: bv?.pe_pct ?? null,
            board_pb_pct: bv?.pb_pct ?? null,
            price: m.price,
            pct_change: m.pct_change,
            total_mktcap: m.total_mktcap,
            pe: m.pe,
            pb: m.pb,
            roe: m.roe,
            net_profit_yoy: m.net_profit_yoy,
            debt_ratio: m.debt_ratio,
            gross_margin: m.gross_margin,
            ocf_to_revenue: m.ocf_to_revenue,
            eps_ttm: m.eps_ttm,
            bps: m.bps,
            rank_in_board: null,
            score: null,
            analysis_id: m.analysis_id,
            is_candidate: false,
          })
        }
      })
      setExtraMembers(extras)
    }).finally(() => { if (!cancelled) setLoadingMembers(false) })
    return () => { cancelled = true }
  }, [includeNonCandidates, run, activeBoards])

  // Filtered candidates for the big table
  const tableCandidates = useMemo(() => {
    let list: CandidateRow[] = includeNonCandidates
      ? [...candidateRows, ...extraMembers]
      : [...candidateRows]
    list = list.filter(passesSectorFilter)
    for (const rule of FILTER_RULES) {
      if (activeRules.has(rule.key)) {
        list = list.filter(rule.test)
      }
    }
    list.sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    return list
  }, [candidateRows, extraMembers, includeNonCandidates, passesSectorFilter, activeRules])

  const sw1Count = run?.summary?.sw1_count ?? 0
  const sw2Count = run?.summary?.sw2_count ?? 0
  const sw1Uv = run?.summary?.sw1_undervalued ?? 0
  const sw2Uv = run?.summary?.sw2_undervalued ?? 0

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">智能选股</h1>
          <p className="text-xs text-gray-500 mt-1">
            扫描申万行业板块估值分位，筛出被低估板块的龙头股
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
            <input type="checkbox" checked={autoAnalyze}
              onChange={(e) => setAutoAnalyze(e.target.checked)} className="accent-accent" />
            自动分析Top3
          </label>
          <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}
            className="bg-surface border border-border rounded px-2 py-1.5 text-xs text-gray-300">
            <option value={1}>快速</option>
            <option value={2}>标准</option>
            <option value={3}>深度</option>
          </select>
          <button onClick={handleRun} disabled={starting || run?.status === "running"}
            className="text-sm px-4 py-1.5 rounded-full bg-accent/15 border border-accent text-accent hover:bg-accent/25 transition-colors disabled:opacity-50">
            {starting || run?.status === "running" ? "筛选中…" : "立即筛选"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 px-3 py-2 rounded bg-red-500/10 border border-red-500/40 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading && <p className="text-gray-500 text-sm">加载中…</p>}

      {!loading && !run && (
        <div className="text-center py-16 text-gray-500">
          <p className="text-3xl mb-3">🔍</p>
          <p className="text-sm">还没有筛选记录，点击右上角「立即筛选」开始。</p>
        </div>
      )}

      {run && (
        <>
          {/* Run meta */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 mb-4">
            <span>日期 {run.run_date}</span>
            {run.summary?.boards_scanned !== undefined && (
              <span>共扫描 {run.summary.boards_scanned} 个板块</span>
            )}
            {sw1Uv > 0 && <span className="text-amber-300">SW1 低估 {sw1Uv}/{sw1Count}</span>}
            {sw2Uv > 0 && <span className="text-amber-300">SW2 低估 {sw2Uv}/{sw2Count}</span>}
            {run.summary?.candidate_count !== undefined && (
              <span>候选 {run.summary.candidate_count} 只</span>
            )}
          </div>

          {run.status === "running" && (
            <div className="px-3 py-2 rounded bg-accent/10 border border-accent/30 text-accent text-sm mb-4">
              {run.error || "正在扫描全市场板块与成分股，约需 1-3 分钟，请稍候…"}
            </div>
          )}
          {run.status === "failed" && (
            <div className="px-3 py-2 rounded bg-red-500/10 border border-red-500/40 text-red-300 text-sm mb-4">
              筛选失败：{run.error}
            </div>
          )}

          {run.status === "complete" && (
            <>
              {/* Tabs */}
              <div className="flex gap-1 mb-4 border-b border-border">
                <button
                  onClick={() => setTab("sw1")}
                  className={`px-4 py-2 text-sm transition-colors border-b-2 ${
                    tab === "sw1"
                      ? "border-accent text-accent font-medium"
                      : "border-transparent text-gray-500 hover:text-gray-300"
                  }`}
                >
                  申万一级（{sw1Count} 个行业）
                  {sw1Uv > 0 && (
                    <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-300">
                      {sw1Uv} 低估
                    </span>
                  )}
                </button>
                <button
                  onClick={() => setTab("sw2")}
                  className={`px-4 py-2 text-sm transition-colors border-b-2 ${
                    tab === "sw2"
                      ? "border-accent text-accent font-medium"
                      : "border-transparent text-gray-500 hover:text-gray-300"
                  }`}
                >
                  申万二级（{sw2Count} 个子行业）
                  {sw2Uv > 0 && (
                    <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-300">
                      {sw2Uv} 低估
                    </span>
                  )}
                </button>
                <button
                  onClick={() => setTab("candidates")}
                  className={`px-4 py-2 text-sm transition-colors border-b-2 ${
                    tab === "candidates"
                      ? "border-accent text-accent font-medium"
                      : "border-transparent text-gray-500 hover:text-gray-300"
                  }`}
                >
                  候选股汇总（{candidates.length} 只）
                </button>
              </div>

              {/* ── Tab: candidates big table ──────────────────────────────── */}
              {tab === "candidates" && (
                <>
                  {/* Valuation filter rules (checkbox, AND-combined) */}
                  <div className="mb-3 rounded border border-border bg-surface p-2.5">
                    <div className="text-xs text-gray-500 mb-2">
                      估值筛选规则（勾选启用，多条规则为「且」关系）
                    </div>
                    <div className="flex flex-col gap-1">
                      {FILTER_RULES.map((rule) => (
                        <label
                          key={rule.key}
                          className={`flex items-start gap-2.5 px-2.5 py-2 rounded border cursor-pointer transition-colors ${
                            activeRules.has(rule.key)
                              ? "border-accent/40 bg-accent/10"
                              : "border-border hover:border-gray-500"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={activeRules.has(rule.key)}
                            onChange={() => toggleRule(rule.key)}
                            className="accent-accent mt-0.5 shrink-0"
                          />
                          <div>
                            <div className={`text-xs font-medium ${activeRules.has(rule.key) ? "text-accent" : "text-gray-300"}`}>
                              {rule.label}
                            </div>
                            <div className="text-[11px] text-gray-500 mt-0.5 leading-relaxed">
                              {rule.description}
                            </div>
                          </div>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Two-level industry filter: 一级行业 -> 二级行业 */}
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span className="text-xs text-gray-500">行业筛选：</span>
                    <MultiSelect
                      options={ALL_SW1}
                      selected={selectedSW1}
                      onChange={setSelectedSW1}
                      placeholder={`全部 ${ALL_SW1.length} 个一级行业`}
                    />
                    <MultiSelect
                      options={sw2Options}
                      selected={selectedSW2}
                      onChange={setSelectedSW2}
                      placeholder={`全部 ${sw2Options.length} 个二级行业`}
                    />
                    {(activeRules.size > 0 || sw1Active || sw2Active) && (
                      <span className="text-xs text-amber-400">
                        共 {tableCandidates.length} 只股票符合条件
                      </span>
                    )}
                  </div>

                  {/* Include non-candidate board members */}
                  <div className="flex items-center gap-2 mb-3">
                    <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={includeNonCandidates}
                        onChange={(e) => setIncludeNonCandidates(e.target.checked)}
                        className="accent-accent"
                      />
                      包含非候选股（默认不含）
                    </label>
                    {includeNonCandidates && loadingMembers && (
                      <span className="text-xs text-gray-500">加载非候选股名单中…</span>
                    )}
                    {includeNonCandidates && !loadingMembers && activeBoards.length > MAX_NON_CANDIDATE_BOARDS && (
                      <span className="text-xs text-amber-400">
                        当前涉及 {activeBoards.length} 个二级行业，超过上限（{MAX_NON_CANDIDATE_BOARDS}个），请缩小行业筛选范围以加载非候选股名单。
                      </span>
                    )}
                    {includeNonCandidates && !loadingMembers && activeBoards.length === 0 && (
                      <span className="text-xs text-gray-500">
                        未筛选出二级行业候选股板块，无法加载非候选股名单。
                      </span>
                    )}
                  </div>

                  {/* Big table */}
                  <div className="overflow-x-auto rounded border border-border bg-surface">
                    <table className="w-full text-xs">
                      <thead className="bg-surface-2 text-gray-400">
                        <tr>
                          <th className="px-2 py-2 text-left font-medium">排名</th>
                          <th className="px-2 py-2 text-left font-medium">代码 / 名称</th>
                          <th className="px-2 py-2 text-left font-medium">所属板块</th>
                          <th className="px-2 py-2 text-right font-medium">评分</th>
                          <th className="px-2 py-2 text-right font-medium">现价</th>
                          <th className="px-2 py-2 text-right font-medium">涨跌</th>
                          <th className="px-2 py-2 text-right font-medium">市值</th>
                          <th className="px-2 py-2 text-right font-medium">PE</th>
                          <th className="px-2 py-2 text-right font-medium">PB</th>
                          <th className="px-2 py-2 text-right font-medium">ROE</th>
                          <th className="px-2 py-2 text-center font-medium">操作</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {tableCandidates.map((c) => (
                          <tr
                            key={`${c.board_name}-${c.ticker}`}
                            onClick={() => navigate(`/screener/stocks/${encodeURIComponent(c.ticker)}`)}
                            className="hover:bg-white/[0.04] cursor-pointer"
                          >
                            <td className="px-2 py-2 text-gray-500">
                              <span className="inline-flex items-center gap-1">
                                {c.is_candidate ? (
                                  <span className="text-[9px] px-1 rounded bg-accent/20 text-accent">候选</span>
                                ) : (
                                  <span className="text-[9px] px-1 rounded bg-surface-2 text-gray-500">非候选</span>
                                )}
                                {c.rank_in_board && <span>#{c.rank_in_board}</span>}
                              </span>
                            </td>
                            <td className="px-2 py-2">
                              <div className="flex flex-col">
                                <span className="font-mono text-gray-400">{c.code || c.ticker}</span>
                                <span className="text-gray-200 truncate max-w-[140px]">{c.ticker_name || "—"}</span>
                              </div>
                            </td>
                            <td className="px-2 py-2 text-gray-400">
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-2 text-gray-300">
                                {c.board_name}
                              </span>
                            </td>
                            <td className="px-2 py-2 text-right font-mono text-accent">
                              {c.score != null ? c.score.toFixed(1) : "—"}
                            </td>
                            <td className="px-2 py-2 text-right text-gray-200">{fmtNum2(c.price)}</td>
                            <td className={`px-2 py-2 text-right ${pctClass(c.pct_change)}`}>
                              {c.pct_change != null
                                ? `${c.pct_change > 0 ? "+" : ""}${c.pct_change.toFixed(2)}%`
                                : "—"}
                            </td>
                            <td className="px-2 py-2 text-right text-gray-300">{fmtYi(c.total_mktcap)}</td>
                            <td className="px-2 py-2 text-right text-gray-300">{fmtNum2(c.pe)}</td>
                            <td className="px-2 py-2 text-right text-gray-300">{fmtNum2(c.pb)}</td>
                            <td className="px-2 py-2 text-right text-gray-300">
                              {c.roe != null ? `${c.roe.toFixed(1)}%` : "—"}
                            </td>
                            <td className="px-2 py-2 text-center">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  if (c.analysis_id) navigate(`/report/${c.analysis_id}`)
                                  else navigate(`/screener/stocks/${encodeURIComponent(c.ticker)}`)
                                }}
                                className="text-[10px] px-2 py-0.5 rounded bg-accent/20 text-accent hover:bg-accent/30"
                              >
                                {c.analysis_id ? "查看" : "详情"}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {tableCandidates.length === 0 && (
                    <p className="text-center py-12 text-sm text-gray-500">
                      {activeRules.size > 0 || sw1Active || sw2Active
                        ? "没有符合所选筛选条件的股票，请尝试取消部分规则或行业筛选。"
                        : "暂无候选股。"}
                    </p>
                  )}
                </>
              )}

              {/* ── Tab: board cards (SW1 / SW2) ──────────────────────────── */}
              {tab !== "candidates" && (
                <>
                  {sortedBoards.length === 0 && (
                    <p className="text-gray-500 text-sm py-8 text-center">该分类下暂无板块数据。</p>
                  )}
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {sortedBoards.map((board) => (
                      <BoardCard
                        key={`${tab}:${board.name}`}
                        board={board}
                        candidateCount={filteredCandidates.filter((c) => c.board_name === board.name).length}
                        onOpen={() => run && navigate(
                          `/screener/runs/${run.id}/boards/${board.level}/${encodeURIComponent(board.name)}`
                        )}
                      />
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
