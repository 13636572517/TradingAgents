// web/src/api/client.ts
import axios from "axios"
import type { Analysis, AnalysisListResponse, ProgressEvent } from "../types"

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
