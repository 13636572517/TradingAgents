// web/src/components/Sidebar.tsx
import { NavLink } from "react-router-dom"
import { useAuth } from "../context/AuthContext"
import { useState, type ReactNode } from "react"

const NAV = [
  { to: "/new",      icon: "＋",  label: "新建分析" },
  { to: "/screener", icon: "🔍",  label: "智能选股" },
  { to: "/history",  icon: "📋",  label: "历史报告" },
  { to: "/strategies", icon: "🎯",  label: "策略看板" },
  { to: "/stats",    icon: "📊",  label: "用量统计" },
  { to: "/settings", icon: "⚙️", label: "设置" },
]

// ── Tooltip wrapper ─────────────────────────────────────────────────────────────

function Tip({ children, text }: { children: ReactNode; text: string }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <div
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        className="cursor-pointer"
      >
        {children}
      </div>
      {show && (
        <span className="absolute left-full top-1/2 -translate-y-1/2 ml-3 whitespace-nowrap rounded px-2.5 py-1 text-xs bg-yellow-100 text-black shadow-md border border-yellow-200 z-50 pointer-events-none">
          {text}
        </span>
      )}
    </div>
  )
}

// ── Sidebar ─────────────────────────────────────────────────────────────────────

interface Props {
  unseen: number
  onHistoryClick: () => void
}

export default function Sidebar({ unseen, onHistoryClick }: Props) {
  const { logout, username, isAdmin } = useAuth()

  return (
    <aside className="hidden md:flex w-14 bg-surface border-r border-border flex-col items-center py-4 gap-6 shrink-0">
      <div className="w-8 h-8 rounded overflow-hidden">
        <img src="/favicon.png" alt="御智投研" className="w-full h-full object-cover" />
      </div>
      {NAV.map((item) =>
        item.to === "/history" ? (
          <Tip key={item.to} text={item.label}>
            <button
              onClick={onHistoryClick}
              className="relative w-10 h-10 flex items-center justify-center rounded hover:bg-accent/10 text-gray-400 hover:text-accent transition-colors text-lg"
            >
              {item.icon}
              {unseen > 0 && (
                <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[9px] rounded-full w-4 h-4 flex items-center justify-center">
                  {unseen > 9 ? "9+" : unseen}
                </span>
              )}
            </button>
          </Tip>
        ) : (
          <Tip key={item.to} text={item.label}>
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                `w-10 h-10 flex items-center justify-center rounded hover:bg-accent/10 transition-colors text-lg ${
                  isActive
                    ? "text-accent bg-accent/10"
                    : "text-gray-400 hover:text-accent"
                }`
              }
            >
              {item.icon}
            </NavLink>
          </Tip>
        )
      )}

      {/* 管理员入口 + 退出按钮，固定在底部 */}
      <div className="mt-auto flex flex-col items-center gap-3">
        {isAdmin && (
          <Tip text="用户管理">
            <NavLink
              to="/admin"
              className={({ isActive }) =>
                `w-10 h-10 flex items-center justify-center rounded hover:bg-accent/10 transition-colors text-lg ${
                  isActive ? "text-accent bg-accent/10" : "text-gray-400 hover:text-accent"
                }`
              }
            >
              👥
            </NavLink>
          </Tip>
        )}
        <Tip text={`退出 (${username ?? ""})`}>
          <button
            onClick={logout}
            className="w-10 h-10 flex items-center justify-center rounded hover:bg-red-500/10 text-gray-400 hover:text-red-400 transition-colors text-lg"
          >
            ⏏
          </button>
        </Tip>
      </div>
    </aside>
  )
}
