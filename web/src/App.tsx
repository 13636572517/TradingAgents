// web/src/App.tsx
import { useEffect, useState } from "react"
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom"
import { AuthProvider, useAuth } from "./context/AuthContext"
import Sidebar from "./components/Sidebar"
import BottomNav from "./components/BottomNav"
import LoginPage from "./pages/LoginPage"
import NewAnalysis from "./pages/NewAnalysis"
import History from "./pages/History"
import Report from "./pages/Report"
import SettingsPage from "./pages/Settings"
import StatsPage from "./pages/StatsPage"
import { api } from "./api/client"

function AppShell() {
  const { token } = useAuth()
  const [unseen, setUnseen] = useState(0)

  useEffect(() => {
    if (!token) return
    const refresh = () => api.getNotificationCount().then((r) => setUnseen(r.unseen))
    refresh()
    const id = setInterval(refresh, 10_000)
    return () => clearInterval(id)
  }, [token])

  if (!token) return <LoginPage />

  return (
    <BrowserRouter>
      <AppLayout unseen={unseen} setUnseen={setUnseen} />
    </BrowserRouter>
  )
}

function AppLayout({ unseen, setUnseen }: { unseen: number; setUnseen: (n: number) => void }) {
  const navigate = useNavigate()

  const handleHistoryClick = async () => {
    if (unseen > 0) await api.markAllRead()
    setUnseen(0)
    navigate("/history")
  }

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      <Sidebar unseen={unseen} onHistoryClick={handleHistoryClick} />
      <main className="flex-1 overflow-y-auto pb-16">
        <Routes>
          <Route path="/" element={<Navigate to="/new" replace />} />
          <Route path="/new" element={<NewAnalysis />} />
          <Route path="/history" element={<History />} />
          <Route path="/report/:id" element={<Report />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/stats" element={<StatsPage />} />
        </Routes>
      </main>
      <BottomNav unseen={unseen} onHistoryClick={handleHistoryClick} />
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  )
}
