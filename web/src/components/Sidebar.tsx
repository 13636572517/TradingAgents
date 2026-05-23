// web/src/components/Sidebar.tsx
import { useEffect, useState } from "react"
import { NavLink, useNavigate } from "react-router-dom"
import { api } from "../api/client"
import { useAuth } from "../context/AuthContext"

const NAV = [
  { to: "/new",      icon: "＋",  label: "新建分析" },
  { to: "/history",  icon: "📋",  label: "历史报告" },
  { to: "/stats",    icon: "📊",  label: "用量统计" },
  { to: "/settings", icon: "⚙️", label: "设置" },
]

export default function Sidebar() {
  const [unseen, setUnseen] = useState(0)
  const navigate = useNavigate()
  const { logout, username } = useAuth()

  useEffect(() => {
    const refresh = () =>
      api.getNotificationCount().then((r) => setUnseen(r.unseen))
    refresh()
    const id = setInterval(refresh, 10_000)
    return () => clearInterval(id)
  }, [])

  const handleHistoryClick = async () => {
    if (unseen > 0) await api.markAllRead()
    setUnseen(0)
    navigate("/history")
  }

  return (
    <aside className="w-14 bg-surface border-r border-border flex flex-col items-center py-4 gap-6 shrink-0">
      <div className="w-8 h-8 rounded bg-accent/20 flex items-center justify-center text-accent font-bold text-sm">
        TA
      </div>
      {NAV.map((item) =>
        item.to === "/history" ? (
          <button
            key={item.to}
            onClick={handleHistoryClick}
            className="relative w-10 h-10 flex items-center justify-center rounded hover:bg-accent/10 text-gray-400 hover:text-accent transition-colors text-lg"
            title={item.label}
          >
            {item.icon}
            {unseen > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[9px] rounded-full w-4 h-4 flex items-center justify-center">
                {unseen > 9 ? "9+" : unseen}
              </span>
            )}
          </button>
        ) : (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `w-10 h-10 flex items-center justify-center rounded hover:bg-accent/10 transition-colors text-lg ${
                isActive
                  ? "text-accent bg-accent/10"
                  : "text-gray-400 hover:text-accent"
              }`
            }
            title={item.label}
          >
            {item.icon}
          </NavLink>
        )
      )}

      {/* 退出按钮，固定在底部 */}
      <div className="mt-auto">
        <button
          onClick={logout}
          className="w-10 h-10 flex items-center justify-center rounded hover:bg-red-500/10 text-gray-400 hover:text-red-400 transition-colors text-lg"
          title={`退出 (${username ?? ""})`}
        >
          ⏏
        </button>
      </div>
    </aside>
  )
}
