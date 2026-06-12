// web/src/pages/Screener.tsx
import { useEffect, useState, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api/client"
import type { ScreeningRun, ScreeningCandidate, UndervaluedBoard } from "../types"

const DEPTH_LABEL: Record<number, string> = { 1: "快速", 2: "标准", 3: "深度" }

function fmtYi(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—"
  return `${(v / 1e8).toFixed(1)}亿`
}

function fmtNum(v: number | null | undefined, suffix = ""): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(1)}${suffix}`
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(0)}%`
}

export default function Screener() {
  const navigate = useNavigate()
  const [run, setRun] = useState<ScreeningRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [autoAnalyze, setAutoAnalyze] = useState(false)
  const [depth, setDepth] = useState(1)
  const [analyzingId, setAnalyzingId] = useState<string | null>(null)
  const [batchBoard, setBatchBoard] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

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

  // Poll while a run is in progress
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

  const handleAnalyze = async (c: ScreeningCandidate) => {
    if (c.analysis_id) { navigate(`/report/${c.analysis_id}`); return }
    setAnalyzingId(c.id)
    try {
      const a = await api.analyzeCandidate(c.id, depth)
      navigate(`/report/${a.id}`)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "分析启动失败")
    } finally {
      setAnalyzingId(null)
    }
  }

  const handleAnalyzeBoard = async (board: string) => {
    if (!run) return
    setBatchBoard(board)
    try {
      await api.analyzeAllCandidates(run.id, depth, board)
      await api.getScreeningRun(run.id).then(setRun)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "批量分析失败")
    } finally {
      setBatchBoard(null)
    }
  }

  const boards: UndervaluedBoard[] = run?.summary?.undervalued_boards ?? []
  const candidates = run?.candidates ?? []
  const byBoard = boards.map((b) => ({
    board: b,
    items: candidates.filter((c) => c.board_name === b.name)
      .sort((a, b2) => (a.rank_in_board ?? 99) - (b2.rank_in_board ?? 99)),
  }))

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">智能选股</h1>
          <p className="text-xs text-gray-500 mt-1">
            扫描A股行业板块估值分位，筛出被低估板块的龙头股，一键发起深度分析
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
            <span>触发 {run.trigger === "scheduled" ? "定时" : "手动"}</span>
            {run.summary?.boards_scanned !== undefined && (
              <span>扫描 {run.summary.boards_scanned} 个板块</span>
            )}
            {run.summary?.undervalued_count !== undefined && (
              <span>低估 {run.summary.undervalued_count} 个</span>
            )}
            {run.summary?.candidate_count !== undefined && (
              <span>候选 {run.summary.candidate_count} 只</span>
            )}
            {run.summary?.roe_available === false && <span className="text-amber-500">ROE数据缺失</span>}
          </div>

          {run.status === "running" && (
            <div className="px-3 py-2 rounded bg-accent/10 border border-accent/30 text-accent text-sm mb-4">
              正在扫描全市场板块与成分股，约需 1-3 分钟，请稍候…
            </div>
          )}
          {run.status === "failed" && (
            <div className="px-3 py-2 rounded bg-red-500/10 border border-red-500/40 text-red-300 text-sm mb-4">
              筛选失败：{run.error}
            </div>
          )}

          {run.status === "complete" && byBoard.length === 0 && (
            <p className="text-gray-500 text-sm py-8 text-center">本次未发现满足条件的低估板块。</p>
          )}

          {/* Boards + candidates */}
          <div className="flex flex-col gap-5">
            {byBoard.map(({ board, items }) => (
              <div key={board.name} className="border border-border rounded-lg bg-surface overflow-hidden">
                {/* Board header */}
                <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 bg-amber-950/15 border-b border-border">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-gray-100">{board.name}</span>
                    <span className="text-xs text-gray-400">
                      PE {fmtNum(board.pe)} · PB {fmtNum(board.pb)}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-buy/10 text-buy border border-buy/30">
                      PE分位 {fmtPct(board.pe_pct)} / PB分位 {fmtPct(board.pb_pct)}
                    </span>
                    {board.valuation_method === "cross_section" && (
                      <span className="text-[10px] text-gray-500" title="历史数据不足，使用同日跨板块横截面分位">横截面</span>
                    )}
                  </div>
                  <button onClick={() => handleAnalyzeBoard(board.name)}
                    disabled={batchBoard === board.name}
                    className="text-xs px-3 py-1 rounded-full border border-border text-gray-400 hover:border-accent hover:text-accent transition-colors disabled:opacity-50">
                    {batchBoard === board.name ? "提交中…" : `一键分析整组 (${DEPTH_LABEL[depth]})`}
                  </button>
                </div>

                {/* Candidates */}
                <div className="divide-y divide-border">
                  {items.map((c) => (
                    <div key={c.id} className="flex items-center gap-3 px-4 py-3 hover:bg-accent/5 transition-colors">
                      <span className="w-6 text-center text-xs text-gray-500">#{c.rank_in_board}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-100 truncate">{c.ticker_name ?? c.ticker}</span>
                          <span className="text-xs text-gray-500">{c.ticker}</span>
                          {c.score !== null && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/10 text-accent">评分 {c.score}</span>
                          )}
                        </div>
                        <div className="text-xs text-gray-500 mt-0.5 flex flex-wrap gap-x-3">
                          <span>市值 {fmtYi(c.total_mktcap)}</span>
                          <span>PE {fmtNum(c.pe)}</span>
                          {c.roe !== null && <span>ROE {fmtNum(c.roe, "%")}</span>}
                          {c.net_inflow !== null && (
                            <span className={c.net_inflow >= 0 ? "text-buy" : "text-sell"}>
                              主力{c.net_inflow >= 0 ? "净流入" : "净流出"} {fmtYi(Math.abs(c.net_inflow))}
                            </span>
                          )}
                        </div>
                      </div>
                      <button onClick={() => handleAnalyze(c)} disabled={analyzingId === c.id}
                        className={`text-xs px-3 py-1.5 rounded-full transition-colors shrink-0 ${
                          c.analysis_id
                            ? "border border-accent/40 text-accent hover:bg-accent/10"
                            : "bg-accent/15 border border-accent text-accent hover:bg-accent/25"
                        } disabled:opacity-50`}>
                        {analyzingId === c.id ? "提交中…" : c.analysis_id ? "查看报告" : "一键分析"}
                      </button>
                    </div>
                  ))}
                  {items.length === 0 && (
                    <p className="px-4 py-3 text-xs text-gray-500">该板块暂无符合条件的龙头股。</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
