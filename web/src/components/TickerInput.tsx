// web/src/components/TickerInput.tsx
import { useState, useRef, useEffect, useCallback } from "react"
import { api } from "../api/client"

interface Suggestion {
  ticker: string
  name: string
  code: string
  market: string
}

interface Props {
  value: string
  onChange: (ticker: string) => void
}

export default function TickerInput({ value, onChange }: Props) {
  const [inputText, setInputText] = useState(value)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle")
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Sync inputText when value changes externally (e.g. pre-filled from URL)
  useEffect(() => {
    setInputText(value)
  }, [value])

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  const search = useCallback((q: string) => {
    if (!q.trim()) {
      setSuggestions([])
      setOpen(false)
      setStatus("idle")
      return
    }

    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort()
    abortRef.current = new AbortController()

    setStatus("loading")
    api
      .searchStocks(q)
      .then((results) => {
        setSuggestions(results)
        setOpen(results.length > 0)
        setActiveIdx(-1)
        setStatus(results.length > 0 ? "done" : "idle")
      })
      .catch((err) => {
        if (err?.name === "CanceledError") return  // aborted, ignore
        setSuggestions([])
        setStatus("error")
      })
  }, [])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const text = e.target.value
    setInputText(text)
    onChange(text)
    setActiveIdx(-1)

    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => search(text), 350)
  }

  const handleSelect = (s: Suggestion) => {
    setInputText(s.ticker)
    onChange(s.ticker)
    setSuggestions([])
    setOpen(false)
    setStatus("idle")
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open || suggestions.length === 0) return
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setActiveIdx((i) => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setActiveIdx((i) => Math.max(i - 1, -1))
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault()
      handleSelect(suggestions[activeIdx])
    } else if (e.key === "Escape") {
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <input
          className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent pr-10"
          placeholder="输入代码或名称，例如：601985 / 宁波银行 / NVDA"
          value={inputText}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => suggestions.length > 0 && setOpen(true)}
          autoComplete="off"
        />
        {/* Status indicator */}
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs">
          {status === "loading" && (
            <span className="text-gray-500 animate-pulse">搜索中…</span>
          )}
          {status === "error" && (
            <span className="text-yellow-600" title="搜索暂时不可用，可直接输入代码">⚠</span>
          )}
        </span>
      </div>

      {/* Dropdown */}
      {open && suggestions.length > 0 && (
        <ul className="absolute z-50 w-full mt-1 bg-surface border border-border rounded-md shadow-xl overflow-hidden">
          {suggestions.map((s, i) => (
            <li
              key={s.ticker}
              onMouseDown={(e) => { e.preventDefault(); handleSelect(s) }}
              className={`flex items-center justify-between px-3 py-2 cursor-pointer text-sm transition-colors ${
                i === activeIdx
                  ? "bg-accent/20 text-white"
                  : "hover:bg-accent/10 text-gray-300"
              }`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-mono text-accent text-xs shrink-0">{s.ticker}</span>
                <span className="truncate">{s.name}</span>
              </div>
              <span className="text-gray-500 text-xs shrink-0 ml-2">{s.market}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
