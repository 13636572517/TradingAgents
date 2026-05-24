// web/src/api/client.ts
import axios from "axios"
import type {
  Analysis, AnalysisListResponse, ProgressEvent, Settings, SettingsUpdate,
  ModelsResponse, Provider, TestResult, AggregateStats, KLineResponse,
  AuthToken, AuthUser, AdminUser, ShareUser,
} from "../types"

const http = axios.create({ baseURL: "/api" })

// ── Request interceptor: inject Bearer token ──────────────────────────────────
http.interceptors.request.use((config) => {
  const token = localStorage.getItem("auth_token")
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ── Response interceptor: 401 → force re-login ────────────────────────────────
let _reloading = false
http.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && !err.config?.url?.includes("/auth/login") && !_reloading) {
      _reloading = true
      localStorage.removeItem("auth_token")
      localStorage.removeItem("auth_username")
      window.location.reload()
    }
    return Promise.reject(err)
  }
)

export const api = {
  // ── Auth ────────────────────────────────────────────────────────────────────
  login: (username: string, password: string) =>
    http.post<AuthToken>("/auth/login", { username, password }).then((r) => r.data),
  getMe: () => http.get<AuthUser>("/auth/me").then((r) => r.data),

  // ── Analyses ────────────────────────────────────────────────────────────────
  createAnalysis: (payload: {
    ticker: string
    trade_date: string
    analysts: string[]
    depth: number
  }) => http.post<Analysis>("/analyses", payload).then((r) => r.data),

  listAnalyses: (skip = 0, limit = 50) =>
    http
      .get<AnalysisListResponse>("/analyses", { params: { skip, limit } })
      .then((r) => r.data),

  getAnalysis: (id: string) =>
    http.get<Analysis>(`/analyses/${id}`).then((r) => r.data),

  deleteAnalysis: (id: string) => http.delete(`/analyses/${id}`),
  stopAnalysis: (id: string) => http.post(`/analyses/${id}/stop`),
  rerunStage: (id: string, stage: string) =>
    http.post<Analysis>(`/analyses/${id}/rerun/${stage}`).then((r) => r.data),

  getNotificationCount: () =>
    http
      .get<{ unseen: number }>("/notifications/count")
      .then((r) => r.data),

  markAllRead: () => http.post("/notifications/read"),

  getSettings: () => http.get<Settings>("/settings").then((r) => r.data),
  saveSettings: (payload: SettingsUpdate) =>
    http.post<Settings>("/settings", payload).then((r) => r.data),
  getModels: (provider: string) =>
    http.get<ModelsResponse>("/settings/models", { params: { provider } }).then((r) => r.data),
  getProviders: () => http.get<Provider[]>("/settings/providers").then((r) => r.data),
  testConnection: () => http.post<TestResult>("/settings/test").then((r) => r.data),
  getFutuStatus: () =>
    http.get<{ connected: boolean; error?: string }>("/settings/futu-status").then((r) => r.data),
  getJQStatus: () =>
    http.get<{ connected: boolean; username?: string; queries_remaining?: number; error?: string }>(
      "/settings/jq-status"
    ).then((r) => r.data),

  getAggregateStats: () =>
    http.get<AggregateStats>("/stats").then((r) => r.data),

  searchStocks: (q: string) =>
    http
      .get<{ ticker: string; name: string; code: string; market: string }[]>(
        "/search",
        { params: { q, limit: 10 } }
      )
      .then((r) => r.data),

  getKLine: (ticker: string, time_range = "1Y", signal?: AbortSignal) =>
    http
      .get<KLineResponse>(`/kline/${encodeURIComponent(ticker)}`, { params: { time_range }, signal })
      .then((r) => r.data),

  // ── Sharing ───────────────────────────────────────────────────────────────────
  getShares: (id: string) => http.get<ShareUser[]>(`/analyses/${id}/shares`).then((r) => r.data),
  addShares: (id: string, user_ids: number[]) =>
    http.post(`/analyses/${id}/shares`, { user_ids }),
  removeShare: (id: string, userId: number) =>
    http.delete(`/analyses/${id}/shares/${userId}`),
  searchUsers: (q: string) =>
    http.get<ShareUser[]>("/auth/users/search", { params: { q } }).then((r) => r.data),

  // ── Admin ─────────────────────────────────────────────────────────────────────
  adminListUsers: () => http.get<AdminUser[]>("/admin/users").then((r) => r.data),
  adminCreateUser: (payload: { username: string; password: string; is_admin: boolean }) =>
    http.post<AdminUser>("/admin/users", payload).then((r) => r.data),
  adminUpdateUser: (id: number, payload: { password?: string; is_active?: boolean; is_admin?: boolean }) =>
    http.put<AdminUser>(`/admin/users/${id}`, payload).then((r) => r.data),
  adminDeleteUser: (id: number) => http.delete(`/admin/users/${id}`),
}

export function openProgressStream(
  analysisId: string,
  onEvent: (event: ProgressEvent) => void,
  onDone: () => void
): EventSource {
  const token = localStorage.getItem("auth_token")
  const url = `/api/analyses/${analysisId}/stream${token ? `?token=${encodeURIComponent(token)}` : ""}`
  const es = new EventSource(url)
  es.onmessage = (e) => {
    const data = JSON.parse(e.data) as ProgressEvent
    onEvent(data)
    if (data.status === "complete" || data.status === "failed" || data.error) {
      es.close()
      onDone()
    }
  }
  es.onerror = () => {
    es.close()
    onDone()
  }
  return es
}
