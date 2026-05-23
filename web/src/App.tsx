// web/src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { AuthProvider, useAuth } from "./context/AuthContext"
import Sidebar from "./components/Sidebar"
import LoginPage from "./pages/LoginPage"
import NewAnalysis from "./pages/NewAnalysis"
import History from "./pages/History"
import Report from "./pages/Report"
import SettingsPage from "./pages/Settings"
import StatsPage from "./pages/StatsPage"

function AppShell() {
  const { token } = useAuth()

  if (!token) return <LoginPage />

  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden bg-bg">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Navigate to="/new" replace />} />
            <Route path="/new" element={<NewAnalysis />} />
            <Route path="/history" element={<History />} />
            <Route path="/report/:id" element={<Report />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/stats" element={<StatsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  )
}
