// web/src/components/BottomNav.tsx
import { NavLink } from "react-router-dom"
import { useAuth } from "../context/AuthContext"

const NAV = [
  { to: "/new",      icon: "＋",  label: "新建" },
  { to: "/history",  icon: "📋",  label: "历史" },
  { to: "/strategies", icon: "🎯",  label: "策略" },
  { to: "/stats",    icon: "📊",  label: "统计" },
  { to: "/settings", icon: "⚙️", label: "设置" },
]

interface Props {
  unseen: number
  onHistoryClick: () => void
}

export default function BottomNav({ unseen, onHistoryClick }: Props) {
  const { logout, isAdmin } = useAuth()

  return (
    <nav className="fixed bottom-0 left-0 right-0 md:hidden bg-surface border-t border-border z-50"
         style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
      <div className="flex">
        {NAV.map((item) =>
          item.to === "/history" ? (
            <button
              key={item.to}
              onClick={onHistoryClick}
              className="flex-1 flex flex-col items-center py-2 gap-0.5 text-gray-400 active:text-accent"
            >
              <span className="text-xl relative">
                {item.icon}
                {unseen > 0 && (
                  <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[9px] rounded-full w-4 h-4 flex items-center justify-center">
                    {unseen > 9 ? "9+" : unseen}
                  </span>
                )}
              </span>
              <span className="text-[10px]">{item.label}</span>
            </button>
          ) : (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex-1 flex flex-col items-center py-2 gap-0.5 transition-colors ${
                  isActive ? "text-accent" : "text-gray-400"
                }`
              }
            >
              <span className="text-xl">{item.icon}</span>
              <span className="text-[10px]">{item.label}</span>
            </NavLink>
          )
        )}
        {isAdmin && (
          <NavLink
            to="/admin"
            className={({ isActive }) =>
              `flex-1 flex flex-col items-center py-2 gap-0.5 transition-colors ${
                isActive ? "text-accent" : "text-gray-400"
              }`
            }
          >
            <span className="text-xl">👥</span>
            <span className="text-[10px]">管理</span>
          </NavLink>
        )}
        <button
          onClick={logout}
          className="flex-1 flex flex-col items-center py-2 gap-0.5 text-gray-400 active:text-red-400"
        >
          <span className="text-xl">⏏</span>
          <span className="text-[10px]">退出</span>
        </button>
      </div>
    </nav>
  )
}
