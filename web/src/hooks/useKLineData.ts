// web/src/hooks/useKLineData.ts
import { useState, useEffect, useRef } from "react"
import { api } from "../api/client"
import type { KLineBar } from "../types"

export type TimeRange = "1M" | "3M" | "6M" | "1Y" | "2Y"

interface KLineState {
  data: KLineBar[]
  loading: boolean
  error: string | null
}

// Module-level cache: key = "TICKER-RANGE", value = KLineBar[]
const _cache = new Map<string, KLineBar[]>()

export function useKLineData(ticker: string, range: TimeRange): KLineState {
  const [state, setState] = useState<KLineState>({ data: [], loading: true, error: null })
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!ticker) return

    const cacheKey = `${ticker}-${range}`
    const cached = _cache.get(cacheKey)

    if (cached) {
      setState({ data: cached, loading: false, error: null })
      return
    }

    // Cancel any in-flight request for the previous range
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setState((s) => ({ ...s, loading: true, error: null }))

    api
      .getKLine(ticker, range, controller.signal)
      .then((resp) => {
        if (controller.signal.aborted) return
        if (resp.error && resp.data.length === 0) {
          setState({ data: [], loading: false, error: resp.error })
        } else {
          _cache.set(cacheKey, resp.data)
          setState({ data: resp.data, loading: false, error: resp.error })
        }
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        setState({ data: [], loading: false, error: String(err) })
      })

    return () => controller.abort()
  }, [ticker, range])

  return state
}
