// web/src/components/ShareModal.tsx
import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import type { ShareUser } from "../types"

interface Props {
  analysisId: string
  onClose: () => void
}

export function ShareModal({ analysisId, onClose }: Props) {
  const [currentShares, setCurrentShares] = useState<ShareUser[]>([])
  const [searchResults, setSearchResults] = useState<ShareUser[]>([])
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<number | null>(null)
  const [removing, setRemoving] = useState<number | null>(null)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    api.getShares(analysisId).then((s) => {
      setCurrentShares(s)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [analysisId])

  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(async () => {
      if (query.trim().length === 0) {
        const all = await api.searchUsers("").catch(() => [])
        setSearchResults(all)
      } else {
        const res = await api.searchUsers(query.trim()).catch(() => [])
        setSearchResults(res)
      }
    }, 200)
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current) }
  }, [query])

  const sharedIds = new Set(currentShares.map((u) => u.id))

  const handleAdd = async (user: ShareUser) => {
    setSaving(user.id)
    try {
      await api.addShares(analysisId, [user.id])
      setCurrentShares((prev) => [...prev, user])
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? "分享失败")
    } finally {
      setSaving(null)
    }
  }

  const handleRemove = async (user: ShareUser) => {
    setRemoving(user.id)
    try {
      await api.removeShare(analysisId, user.id)
      setCurrentShares((prev) => prev.filter((u) => u.id !== user.id))
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? "撤销失败")
    } finally {
      setRemoving(null)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-border rounded-xl w-full max-w-sm shadow-xl flex flex-col max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <h3 className="text-base font-semibold text-white">分享报告</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors text-lg leading-none">×</button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* Current shares */}
          <div>
            <p className="text-xs text-gray-500 mb-2">已分享给</p>
            {loading ? (
              <p className="text-xs text-gray-600">加载中…</p>
            ) : currentShares.length === 0 ? (
              <p className="text-xs text-gray-600">尚未分享给任何人</p>
            ) : (
              <div className="space-y-1">
                {currentShares.map((u) => (
                  <div key={u.id} className="flex items-center justify-between px-3 py-1.5 rounded bg-accent/10 border border-accent/20">
                    <span className="text-sm text-white">👤 {u.username}</span>
                    <button
                      onClick={() => handleRemove(u)}
                      disabled={removing === u.id}
                      className="text-xs text-red-400 hover:text-red-300 disabled:opacity-40 ml-3"
                    >
                      {removing === u.id ? "…" : "撤销"}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Search & add */}
          <div>
            <p className="text-xs text-gray-500 mb-2">添加用户</p>
            <input
              className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-accent"
              placeholder="搜索用户名…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
            />
            <div className="mt-2 space-y-1 max-h-48 overflow-y-auto">
              {searchResults.length === 0 && query.trim() !== "" && (
                <p className="text-xs text-gray-600 px-1">无匹配用户</p>
              )}
              {searchResults.map((u) => {
                const already = sharedIds.has(u.id)
                return (
                  <div key={u.id} className="flex items-center justify-between px-3 py-1.5 rounded hover:bg-white/5">
                    <span className="text-sm text-gray-300">👤 {u.username}</span>
                    {already ? (
                      <span className="text-xs text-accent">已分享</span>
                    ) : (
                      <button
                        onClick={() => handleAdd(u)}
                        disabled={saving === u.id}
                        className="text-xs text-accent hover:underline disabled:opacity-40"
                      >
                        {saving === u.id ? "…" : "+ 分享"}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div className="px-5 py-3 border-t border-border shrink-0">
          <button
            onClick={onClose}
            className="w-full text-sm py-2 rounded border border-border text-gray-400 hover:text-white hover:border-gray-500 transition-colors"
          >
            完成
          </button>
        </div>
      </div>
    </div>
  )
}
