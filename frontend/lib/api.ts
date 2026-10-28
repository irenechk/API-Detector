// Use relative URLs by default (works through nginx proxy & ngrok tunnel).
// Set NEXT_PUBLIC_API_URL to override (e.g. for direct backend access).
const API_BASE = process.env.NEXT_PUBLIC_API_URL || ''

async function fetchText(endpoint: string): Promise<string> {
  const res = await fetch(`${API_BASE}${endpoint}`)
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  return res.text()
}

async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }

  return res.json()
}

export const api = {
  // Dashboard
  getDashboard: () => fetchAPI<any>('/api/v1/dashboard'),
  getScoreboard: () => fetchAPI<any>('/api/v1/scoreboard'),

  // Inventory
  getInventory: (params?: Record<string, string>) => {
    const query = params ? '?' + new URLSearchParams(params).toString() : ''
    return fetchAPI<any>(`/api/v1/inventory${query}`)
  },
  getAPIDetail: (id: string) => fetchAPI<any>(`/api/v1/inventory/${id}`),
  getAPIRisk: (id: string) => fetchAPI<any>(`/api/v1/inventory/${id}/risk`),
  getAPISecurity: (id: string) => fetchAPI<any>(`/api/v1/inventory/${id}/security`),

  // Actions
  quarantineAPI: (id: string) =>
    fetchAPI<any>(`/api/v1/inventory/${id}/quarantine`, { method: 'POST' }),
  rescueAPI: (id: string) =>
    fetchAPI<any>(`/api/v1/inventory/${id}/rescue`, { method: 'POST' }),
  decommissionAPI: (id: string) =>
    fetchAPI<any>(`/api/v1/inventory/${id}/decommission`, { method: 'POST' }),

  // Zombies & Shadows
  getZombies: () => fetchAPI<any>('/api/v1/zombies'),
  getShadows: () => fetchAPI<any>('/api/v1/shadows'),

  // Reports
  exportReport: (id: string) =>
    fetchAPI<any>(`/api/v1/reports/${id}/export`, { method: 'POST' }),

  // Scanner
  scanURL: (url: string) =>
    fetchAPI<any>('/api/v1/scanner/scan', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
  getScanResults: () => fetchAPI<any>('/api/v1/scanner/results'),
  clearScanResults: () =>
    fetchAPI<any>('/api/v1/scanner/results', { method: 'DELETE' }),

  // ML & Governance
  getStatusPrediction: (id: string) => fetchAPI<any>(`/api/v1/ml/status/${id}`),
  getMLModels: (modelType?: string) =>
    fetchAPI<any>(`/api/v1/ml/models${modelType ? `?model_type=${encodeURIComponent(modelType)}` : ''}`),
  getModelCard: (modelType: string, version: string) =>
    fetchText(`/api/v1/ml/models/${encodeURIComponent(modelType)}/${encodeURIComponent(version)}/card`),
  promoteModel: (modelType: string, version: string) =>
    fetchAPI<any>(`/api/v1/ml/models/${encodeURIComponent(modelType)}/${encodeURIComponent(version)}/promote`, {
      method: 'POST',
    }),
  getDrift: () => fetchAPI<any>('/api/v1/ml/monitoring/drift'),
  setDriftBaseline: () =>
    fetchAPI<any>('/api/v1/ml/monitoring/baseline', {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  // Notifications (Pending Quarantines)
  getPendingQuarantines: () => fetchAPI<any>('/api/v1/notifications/pending-quarantines'),
  approvePendingQuarantine: (pqId: string) =>
    fetchAPI<any>(`/api/v1/notifications/pending-quarantines/${pqId}/approve`, { method: 'POST' }),
  dismissPendingQuarantine: (pqId: string) =>
    fetchAPI<any>(`/api/v1/notifications/pending-quarantines/${pqId}/dismiss`, { method: 'POST' }),

  // Health
  health: () => fetchAPI<any>('/api/v1/health'),
}
