import { create } from 'zustand'

interface UIState {
  sidebarOpen: boolean
  darkMode: boolean
  toggleSidebar: () => void
  toggleDarkMode: () => void
  setDarkMode: (value: boolean) => void
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  darkMode: false,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  toggleDarkMode: () =>
    set((state) => {
      const newMode = !state.darkMode
      if (typeof window !== 'undefined') {
        document.documentElement.classList.toggle('dark', newMode)
      }
      return { darkMode: newMode }
    }),
  setDarkMode: (value: boolean) => {
    if (typeof window !== 'undefined') {
      document.documentElement.classList.toggle('dark', value)
    }
    set({ darkMode: value })
  },
}))

interface AuthState {
  user: any | null
  isAuthenticated: boolean
  setUser: (user: any) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  setUser: (user) => set({ user, isAuthenticated: true }),
  logout: () => set({ user: null, isAuthenticated: false }),
}))

interface FilterState {
  filters: Record<string, string>
  searchQuery: string
  setFilter: (key: string, value: string) => void
  setSearchQuery: (q: string) => void
  clearFilters: () => void
}

export const useFilterStore = create<FilterState>((set) => ({
  filters: {},
  searchQuery: '',
  setFilter: (key, value) =>
    set((state) => ({ filters: { ...state.filters, [key]: value } })),
  setSearchQuery: (q) => set({ searchQuery: q }),
  clearFilters: () => set({ filters: {}, searchQuery: '' }),
}))

interface PendingQuarantineItem {
  id: string
  api_id: string
  endpoint_path: string
  http_method: string
  environment: string
  risk_score: number
  owner_team: string | null
  reason: string
  detected_at: string
}

interface QuarantineNotificationState {
  pendingItems: PendingQuarantineItem[]
  loading: boolean
  error: string | null
  fetchPending: () => Promise<void>
  approveQuarantine: (pqId: string) => Promise<void>
  dismissQuarantine: (pqId: string) => Promise<void>
}

export const useQuarantineNotificationStore = create<QuarantineNotificationState>((set, get) => ({
  pendingItems: [],
  loading: false,
  error: null,

  fetchPending: async () => {
    set({ loading: true, error: null })
    try {
      const res = await fetch('/api/v1/notifications/pending-quarantines')
      if (!res.ok) throw new Error('Failed to fetch pending quarantines')
      const json = await res.json()
      set({ pendingItems: json.data || [], loading: false })
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  },

  approveQuarantine: async (pqId: string) => {
    try {
      const res = await fetch(`/api/v1/notifications/pending-quarantines/${pqId}/approve`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to approve quarantine')
      set((state) => ({
        pendingItems: state.pendingItems.filter((item) => item.id !== pqId),
      }))
    } catch (e: any) {
      set({ error: e.message })
    }
  },

  dismissQuarantine: async (pqId: string) => {
    try {
      const res = await fetch(`/api/v1/notifications/pending-quarantines/${pqId}/dismiss`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to dismiss')
      set((state) => ({
        pendingItems: state.pendingItems.filter((item) => item.id !== pqId),
      }))
    } catch (e: any) {
      set({ error: e.message })
    }
  },
}))
