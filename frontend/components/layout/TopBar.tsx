'use client'

import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import {
  Search, Moon, Sun, LogOut, ChevronDown, Settings,
  Bell, Shield, ShieldOff, AlertTriangle, Clock,
} from 'lucide-react'
import { signOut } from 'next-auth/react'
import { useUIStore, useFilterStore, useQuarantineNotificationStore } from '@/lib/store'
import { formatDistanceToNow } from 'date-fns'

export function TopBar() {
  const router = useRouter()
  const { darkMode, toggleDarkMode } = useUIStore()
  const { searchQuery, setSearchQuery } = useFilterStore()
  const {
    pendingItems, fetchPending, approveQuarantine, dismissQuarantine,
  } = useQuarantineNotificationStore()

  const [menuOpen, setMenuOpen] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const notifRef = useRef<HTMLDivElement>(null)
  const [approving, setApproving] = useState<string | null>(null)
  const [dismissing, setDismissing] = useState<string | null>(null)

  useEffect(() => {
    fetchPending()
    const interval = setInterval(fetchPending, 30000)
    return () => clearInterval(interval)
  }, [fetchPending])

  useEffect(() => {
    if (!menuOpen) return
    const handle = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [menuOpen])

  useEffect(() => {
    if (!notifOpen) return
    const handle = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotifOpen(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [notifOpen])

  const handleApprove = async (pqId: string) => {
    setApproving(pqId)
    await approveQuarantine(pqId)
    setApproving(null)
  }

  const handleDismiss = async (pqId: string) => {
    setDismissing(pqId)
    await dismissQuarantine(pqId)
    setDismissing(null)
  }

  const riskColor = (score: number) => {
    if (score >= 80) return 'text-red-500'
    if (score >= 60) return 'text-orange-500'
    if (score >= 40) return 'text-yellow-500'
    return 'text-green-500'
  }

  return (
    <header className="h-16 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-6">
      <div className="flex-1 max-w-md">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search APIs, endpoints, owners..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-900 dark:text-white placeholder-gray-400"
          />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={toggleDarkMode}
          className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500"
        >
          {darkMode ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        {/* Notification Bell */}
        <div ref={notifRef} className="relative">
          <button
            onClick={() => setNotifOpen(!notifOpen)}
            className="relative p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 transition-colors"
          >
            <Bell size={18} />
            {pendingItems.length > 0 && (
              <span className="absolute -top-0.5 -right-0.5 w-4.5 h-4.5 flex items-center justify-center bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[18px] min-h-[18px] leading-none">
                {pendingItems.length}
              </span>
            )}
          </button>

          {notifOpen && (
            <div className="absolute right-0 top-full mt-2 w-96 bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 z-50 max-h-[70vh] flex flex-col">
              <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 flex items-center justify-between shrink-0">
                <div>
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">Pending Quarantines</p>
                  <p className="text-xs text-gray-500">
                    {pendingItems.length} API{pendingItems.length !== 1 ? 's' : ''} awaiting approval
                  </p>
                </div>
                <Shield className="w-5 h-5 text-amber-500" />
              </div>

              <div className="overflow-y-auto flex-1">
                {pendingItems.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-10 text-gray-400">
                    <ShieldOff size={32} className="mb-2" />
                    <p className="text-sm">No pending quarantines</p>
                    <p className="text-xs mt-1">All clear — no APIs await action</p>
                  </div>
                ) : (
                  <div className="divide-y divide-gray-100 dark:divide-gray-700">
                    {pendingItems.map((item) => (
                      <div key={item.id} className="px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs font-mono text-gray-400 uppercase">{item.http_method}</span>
                              <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                                {item.endpoint_path}
                              </span>
                            </div>
                            <div className="flex items-center gap-2 mt-1">
                              <span className={`text-xs font-semibold ${riskColor(item.risk_score)}`}>
                                Risk: {item.risk_score}
                              </span>
                              <span className="text-xs text-gray-400">{item.environment}</span>
                              {item.owner_team && (
                                <span className="text-xs text-gray-400 truncate">{item.owner_team}</span>
                              )}
                            </div>
                            <div className="flex items-start gap-1.5 mt-1.5">
                              <AlertTriangle size={12} className="text-amber-500 mt-0.5 shrink-0" />
                              <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">{item.reason}</p>
                            </div>
                            <div className="flex items-center gap-1 mt-1.5 text-[10px] text-gray-400">
                              <Clock size={10} />
                              <span>Detected {formatDistanceToNow(new Date(item.detected_at), { addSuffix: true })}</span>
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center justify-end gap-2 mt-2">
                          <button
                            onClick={() => handleDismiss(item.id)}
                            disabled={dismissing === item.id}
                            className="px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors disabled:opacity-50"
                          >
                            {dismissing === item.id ? '...' : 'Dismiss'}
                          </button>
                          <button
                            onClick={() => handleApprove(item.id)}
                            disabled={approving === item.id}
                            className="px-3 py-1.5 text-xs font-medium text-white bg-red-500 hover:bg-red-600 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1"
                          >
                            {approving === item.id ? (
                              '...'
                            ) : (
                              <>
                                <Shield size={12} />
                                Quarantine
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {pendingItems.length > 0 && (
                <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-700 shrink-0">
                  <button
                    onClick={() => router.push('/zombie-graveyard')}
                    className="w-full text-center text-xs text-blue-500 hover:text-blue-600 font-medium py-1"
                  >
                    View all in Zombie Graveyard →
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* User Dropdown */}
        <div ref={menuRef} className="relative pl-2 border-l border-gray-200 dark:border-gray-700">
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="flex items-center gap-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 px-2 py-1.5 transition-colors"
          >
            <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white text-xs font-bold">
              AD
            </div>
            <div className="hidden md:block text-left">
              <p className="text-sm font-medium text-gray-900 dark:text-white">Azure AD</p>
              <p className="text-xs text-gray-500">Signed In</p>
            </div>
            <ChevronDown size={14} className="text-gray-400" />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-2 w-56 bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 z-50 py-1.5">
              <div className="px-4 py-2 border-b border-gray-100 dark:border-gray-700">
                <p className="text-sm font-medium text-gray-900 dark:text-white">Azure AD User</p>
                <p className="text-xs text-gray-500">Signed in with Microsoft</p>
              </div>
              <div className="py-1">
                <button
                  onClick={() => { setMenuOpen(false); router.push('/settings') }}
                  className="flex items-center gap-2.5 w-full px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                >
                  <Settings size={16} className="text-gray-400" />
                  Settings
                </button>
              </div>
              <div className="border-t border-gray-100 dark:border-gray-700 pt-1">
                <button
                  onClick={() => { setMenuOpen(false); signOut({ callbackUrl: '/login' }) }}
                  className="flex items-center gap-2.5 w-full px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                >
                  <LogOut size={16} />
                  Sign Out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
