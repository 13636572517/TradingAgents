// web/src/api/client.ts
import axios from "axios"
import type { Analysis, AnalysisListResponse, ProgressEvent, Settings, SettingsUpdate, ModelsResponse, Provider, TestResult, AggregateStats } from "../types"

const http = axios.create({ baseURL: "/api" })

export const api = {
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

  getAggregateStats: () =>
    http.get<AggregateStats>("/stats").then((r) => r.data),

  searchStocks: (q: string) =>
    http
      .get<{ ticker: string; name: string; code: string; market: string }[]>(
        "/search",
        { params: { q, limit: 10 } }
      )
      .then((r) => r.data),
}

export function openProgressStream(
  analysisId: string,
  onEvent: (event: ProgressEvent) => void,
  onDone: () => void
): EventSource {
  const es = new EventSource(`/api/analyses/${analysisId}/stream`)
  es.onmessage = (e) => {
    const data = JSON.parse(e.data) as ProgressEvent
    onEvent(data)
    if (
      data.status === "complete" ||
      data.status === "failed" ||
      data.error
    ) {
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
