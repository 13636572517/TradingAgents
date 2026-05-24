// web/src/pages/AdminPage.tsx
import { useEffect, useState } from "react"
import { api } from "../api/client"
import type { AdminUser } from "../types"

// ── helpers ───────────────────────────────────────────────────────────────────
function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
  })
}

// ── Create / Edit modal ───────────────────────────────────────────────────────
function UserModal({
  user,
  onClose,
  onSaved,
}: {
  user: AdminUser | null
  onClose: () => void
  onSaved: () => void
}) {
  const isCreate = user === null
  const [username, setUsername] = useState(user?.username ?? "")
  const [password, setPassword] = useState("")
  const [isAdmin, setIsAdmin] = useState(user?.is_admin ?? false)
  const [isActive, setIsActive] = useState(user?.is_active ?? true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSave = async () => {
    if (isCreate && !username.trim()) { setError("用户名不能为空"); return }
    if (isCreate && password.length < 4) { setError("密码至少 4 位"); return }
    if (!isCreate && password && password.length < 4) { setError("密码至少 4 位"); return }
    setSaving(true)
    setError(null)
    try {
      if (isCreate) {
        await api.adminCreateUser({ username: username.trim(), password, is_admin: isAdmin })
      } else {
        const payload: { password?: string; is_active?: boolean; is_admin?: boolean } = {
          is_active: isActive,
          is_admin: isAdmin,
        }
        if (password) payload.password = password
        await api.adminUpdateUser(user!.id, payload)
      }
      onSaved()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "操作失败")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-border rounded-xl w-full max-w-sm p-6 shadow-xl">
        <h3 className="text-base font-semibold text-white mb-5">
          {isCreate ? "新建账号" : `编辑：${user!.username}`}
        </h3>

        <div className="space-y-4">
          {isCreate && (
            <div>
              <label className="text-xs text-gray-400 mb-1 block">用户名</label>
              <input
                className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-accent"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="登录用户名"
                autoFocus
              />
            </div>
          )}

          <div>
            <label className="text-xs text-gray-400 mb-1 block">
              {isCreate ? "初始密码" : "重置密码（留空不改）"}
            </label>
            <input
              type="password"
              className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-accent"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isCreate ? "至少 4 位" : "留空则不修改"}
            />
          </div>

          <div className="flex gap-6">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                className="accent-accent"
                checked={isAdmin}
                onChange={(e) => setIsAdmin(e.target.checked)}
              />
              <span className="text-sm text-gray-300">管理员</span>
            </label>
            {!isCreate && (
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  className="accent-accent"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                />
                <span className="text-sm text-gray-300">启用账号</span>
              </label>
            )}
          </div>
        </div>

        {error && <p className="text-red-400 text-xs mt-3">{error}</p>}

        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-sm bg-accent text-bg rounded hover:bg-accent/90 transition-colors disabled:opacity-50"
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function AdminPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modalUser, setModalUser] = useState<AdminUser | "new" | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setUsers(await api.adminListUsers())
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleDelete = async (user: AdminUser) => {
    if (!confirm(`确认删除用户「${user.username}」？此操作不可撤销。`)) return
    setDeleting(user.id)
    try {
      await api.adminDeleteUser(user.id)
      await load()
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? "删除失败")
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-white">用户管理</h1>
          <p className="text-xs text-gray-500 mt-0.5">管理员可创建、编辑和删除会员账号</p>
        </div>
        <button
          onClick={() => setModalUser("new")}
          className="text-sm px-4 py-2 bg-accent text-bg rounded hover:bg-accent/90 transition-colors font-medium"
        >
          + 新建账号
        </button>
      </div>

      {loading && <p className="text-gray-400 text-sm">加载中…</p>}
      {error && <p className="text-red-400 text-sm">{error}</p>}

      {!loading && !error && (
        <div className="bg-surface border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-gray-500 uppercase">
                <th className="text-left px-4 py-3">用户名</th>
                <th className="text-left px-4 py-3">角色</th>
                <th className="text-left px-4 py-3">状态</th>
                <th className="text-left px-4 py-3">创建时间</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-border/50 last:border-0 hover:bg-white/3 transition-colors">
                  <td className="px-4 py-3 text-white font-medium">{u.username}</td>
                  <td className="px-4 py-3">
                    {u.is_admin ? (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-accent/20 text-accent border border-accent/30">
                        管理员
                      </span>
                    ) : (
                      <span className="text-xs text-gray-500">会员</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active ? (
                      <span className="text-xs text-buy">● 启用</span>
                    ) : (
                      <span className="text-xs text-gray-600">● 禁用</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500">{fmtDate(u.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => setModalUser(u)}
                        className="text-xs text-accent hover:underline"
                      >
                        编辑
                      </button>
                      <button
                        onClick={() => handleDelete(u)}
                        disabled={deleting === u.id}
                        className="text-xs text-red-400 hover:underline disabled:opacity-40"
                      >
                        {deleting === u.id ? "删除中…" : "删除"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-500">暂无用户</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {modalUser !== null && (
        <UserModal
          user={modalUser === "new" ? null : modalUser}
          onClose={() => setModalUser(null)}
          onSaved={() => { setModalUser(null); load() }}
        />
      )}
    </div>
  )
}
