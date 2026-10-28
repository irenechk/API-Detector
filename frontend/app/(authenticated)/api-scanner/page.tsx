'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { formatDate } from '@/lib/utils'
import toast from 'react-hot-toast'
import {
  Search, Globe, Loader2, CheckCircle, XCircle,
  ChevronDown, ChevronUp, Trash2, Clock, FileText,
  Shield, AlertTriangle, Skull, Bug, Lock, Activity,
} from 'lucide-react'

const TABS = ['scanner', 'scanned-inventory']

const CONFIDENCE_COLORS: Record<string, string> = {
  high: 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
  medium: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-300',
  low: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
}

const SOURCE_LABELS: Record<string, string> = {
  html_link: 'HTML Link',
  script_hardcoded: 'Script Reference',
  common_pattern: 'Pattern Match',
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300 border-red-200 dark:border-red-800',
  high: 'bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300 border-orange-200 dark:border-orange-800',
  medium: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-300 border-yellow-200 dark:border-yellow-800',
  low: 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300 border-blue-200 dark:border-blue-800',
}

const SEVERITY_ICONS: Record<string, any> = {
  critical: Skull,
  high: AlertTriangle,
  medium: Bug,
  low: Lock,
}

export default function ApiScannerPage() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState('scanner')
  const [targetUrl, setTargetUrl] = useState('')
  const [expandedResult, setExpandedResult] = useState<string | null>(null)
  const [scanUrl, setScanUrl] = useState<string | null>(null)

  const scanMutation = useMutation({
    mutationFn: (url: string) => api.scanURL(url),
    onSuccess: (data) => {
      toast.success(`Found ${data?.data?.total_found || 0} API endpoints`)
      queryClient.invalidateQueries({ queryKey: ['scan-results'] })
    },
    onError: () => toast.error('Failed to scan URL'),
  })

  const { data: scanResults, isLoading: resultsLoading } = useQuery({
    queryKey: ['scan-results'],
    queryFn: () => api.getScanResults(),
  })

  const handleScan = (e: React.FormEvent) => {
    e.preventDefault()
    if (!targetUrl.trim()) {
      toast.error('Please enter a URL')
      return
    }
    setScanUrl(targetUrl.trim())
    setActiveTab('scanned-inventory')
    scanMutation.mutate(targetUrl.trim())
  }

  const allResults = scanResults?.data?.results || []
  const scanData = scanMutation.data?.data

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-page-title text-gray-900 dark:text-white">API Scanner</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Discover API endpoints by scanning websites
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-white dark:bg-gray-800 rounded-card shadow-card p-1">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 py-2.5 text-sm font-medium rounded-lg capitalize transition-colors ${
              activeTab === tab
                ? 'bg-blue-600 text-white'
                : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            {tab === 'scanner' ? 'Scanner' : 'Scanned Inventory'}
          </button>
        ))}
      </div>

      {activeTab === 'scanner' && (
        <div className="bg-white dark:bg-gray-800 rounded-card shadow-card p-6">
          <form onSubmit={handleScan} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Enter Website URL
              </label>
              <div className="flex gap-3">
                <div className="relative flex-1">
                  <Globe className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="url"
                    value={targetUrl}
                    onChange={(e) => setTargetUrl(e.target.value)}
                    placeholder="https://example.com"
                    className="w-full pl-12 pr-4 py-3 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-900 dark:text-white placeholder-gray-400"
                  />
                </div>
                <button
                  type="submit"
                  disabled={scanMutation.isPending}
                  className="px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-xl text-sm font-medium transition-colors flex items-center gap-2"
                >
                  {scanMutation.isPending ? (
                    <Loader2 size={18} className="animate-spin" />
                  ) : (
                    <Search size={18} />
                  )}
                  Scan
                </button>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800">
              <p className="text-sm text-blue-700 dark:text-blue-300 font-medium mb-1">How it works</p>
              <ul className="text-xs text-blue-600 dark:text-blue-400 space-y-1">
                <li>• Fetches the webpage and analyzes HTML for API patterns</li>
                <li>• Detects links to /api/, /v1/, /rest/, /graphql endpoints</li>
                <li>• Scans script contents for hardcoded API URLs</li>
                <li>• Matches against common API endpoint patterns</li>
              </ul>
            </div>
          </form>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-4 mt-6">
            <div className="text-center p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
              <p className="text-2xl font-bold text-blue-500">{allResults.length}</p>
              <p className="text-xs text-gray-500 mt-0.5">Total Discovered</p>
            </div>
            <div className="text-center p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
              <p className="text-2xl font-bold text-green-500">
                {allResults.filter((r: any) => r.confidence === 'high').length}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">High Confidence</p>
            </div>
            <div className="text-center p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
              <p className="text-2xl font-bold text-yellow-500">
                {scanMutation.data?.data?.total_found || 0}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">Last Scan</p>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'scanned-inventory' && (
        <div className="space-y-4">
          {scanMutation.isPending && (
            <div className="bg-white dark:bg-gray-800 rounded-card shadow-card p-8">
              <div className="flex flex-col items-center gap-3">
                <Loader2 size={32} className="animate-spin text-blue-500" />
                <p className="text-sm text-gray-500">Scanning {scanUrl}...</p>
              </div>
            </div>
          )}

          {scanMutation.isError && (
            <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-card p-6 text-center">
              <XCircle size={32} className="text-red-500 mx-auto mb-2" />
              <p className="text-sm text-red-600 dark:text-red-400">Failed to scan URL</p>
              <button
                onClick={() => scanMutation.mutate(targetUrl)}
                className="mt-3 text-sm text-blue-600 hover:underline"
              >
                Try Again
              </button>
            </div>
          )}

          {!scanMutation.isPending && !scanMutation.isError && (
            <>
              {scanData && (
                <div className="bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-900/50 rounded-card p-4">
                  <div className="flex items-center gap-2">
                    <CheckCircle size={18} className="text-green-500" />
                    <p className="text-sm text-green-700 dark:text-green-300 font-medium">
                      Scan complete — found {scanData.total_found} API endpoints on <strong>{scanData.scan_url}</strong>
                    </p>
                  </div>
                </div>
              )}

              {allResults.length === 0 && !scanData && (
                <div className="bg-white dark:bg-gray-800 rounded-card shadow-card p-12 text-center">
                  <Search size={48} className="text-gray-300 dark:text-gray-600 mx-auto mb-3" />
                  <p className="text-gray-400 text-sm">No scan results yet</p>
                  <p className="text-xs text-gray-400 mt-1">
                    Go to the Scanner tab and enter a URL to discover APIs
                  </p>
                </div>
              )}

              {allResults.length > 0 && (
                <div className="bg-white dark:bg-gray-800 rounded-card shadow-card overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                    <h2 className="text-section-title text-gray-900 dark:text-white">
                      Discovered Endpoints ({allResults.length})
                    </h2>
                    <button
                      onClick={async () => {
                        try {
                          await api.clearScanResults()
                          queryClient.invalidateQueries({ queryKey: ['scan-results'] })
                          toast.success('Results cleared')
                        } catch {
                          toast.error('Failed to clear results')
                        }
                      }}
                      className="flex items-center gap-1 text-xs px-2.5 py-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 rounded-lg transition-colors"
                    >
                      <Trash2 size={14} />
                      Clear
                    </button>
                  </div>
                  <div className="divide-y divide-gray-100 dark:divide-gray-700/50">
                    {allResults.map((result: any) => (
                      <div key={result.id}>
                        <div
                          className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/30 cursor-pointer transition-colors"
                          onClick={() => setExpandedResult(expandedResult === result.id ? null : result.id)}
                        >
                          <div className="flex items-center gap-3 min-w-0 flex-1">
                            <span className={`px-1.5 py-0.5 text-xs font-mono font-medium rounded ${
                              result.http_method === 'GET' ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300' :
                              result.http_method === 'POST' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300' :
                              result.http_method === 'PUT' ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300' :
                              'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300'
                            }`}>
                              {result.http_method}
                            </span>
                            <span className="font-mono text-xs text-gray-900 dark:text-white truncate">
                              {result.endpoint_path}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0">
                            {result.security && (
                              <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${
                                result.security.overall_severity === 'critical' ? 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300 border-red-300 dark:border-red-700 animate-pulse-border' :
                                result.security.overall_severity === 'high' ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300 border-orange-300 dark:border-orange-700' :
                                result.security.overall_severity === 'medium' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-300 border-yellow-300 dark:border-yellow-700' :
                                'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300 border-blue-300 dark:border-blue-700'
                              }`}>
                                {result.security.overall_severity}
                              </span>
                            )}
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CONFIDENCE_COLORS[result.confidence] || ''}`}>
                              {result.confidence}
                            </span>
                            {expandedResult === result.id ? (
                              <ChevronUp size={14} className="text-gray-400" />
                            ) : (
                              <ChevronDown size={14} className="text-gray-400" />
                            )}
                          </div>
                        </div>
                        {expandedResult === result.id && (
                          <div className="px-4 pb-4 pl-[72px] space-y-3">
                            {/* Basic info */}
                            <div className="grid grid-cols-2 gap-2 text-xs text-gray-500">
                              <div className="flex items-center gap-1">
                                <FileText size={12} />
                                <span>Source: {SOURCE_LABELS[result.source] || result.source}</span>
                              </div>
                              <div className="flex items-center gap-1">
                                <Clock size={12} />
                                <span>Found: {new Date(result.discovered_at).toLocaleString()}</span>
                              </div>
                              <div className="flex items-center gap-1 col-span-2">
                                <Globe size={12} />
                                <span className="truncate">From: {result.scan_url}</span>
                              </div>
                            </div>

                            {/* ML Classification */}
                            {result.ml_enhanced && (
                              <div className="space-y-2 pt-2 border-t border-gray-100 dark:border-gray-700">
                                <div className="flex items-center gap-1.5">
                                  <Activity size={13} className="text-blue-500" />
                                  <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                                    ML Classification
                                  </span>
                                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
                                    {result.ml_enhanced.ml_model_version}
                                  </span>
                                </div>
                                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                                  <div className="p-2 rounded-lg bg-gray-50 dark:bg-gray-700/40">
                                    <p className="text-[10px] uppercase tracking-wider text-gray-400">Category</p>
                                    <p className="font-medium text-gray-900 dark:text-white capitalize">
                                      {String(result.ml_enhanced.category || 'unknown').replace(/_/g, ' ')}
                                    </p>
                                  </div>
                                  <div className="p-2 rounded-lg bg-gray-50 dark:bg-gray-700/40">
                                    <p className="text-[10px] uppercase tracking-wider text-gray-400">Severity</p>
                                    <p className="font-medium text-gray-900 dark:text-white capitalize">
                                      {result.ml_enhanced.severity || 'unknown'}
                                    </p>
                                  </div>
                                  <div className="p-2 rounded-lg bg-gray-50 dark:bg-gray-700/40">
                                    <p className="text-[10px] uppercase tracking-wider text-gray-400">Risk Score</p>
                                    <p className="font-medium text-gray-900 dark:text-white">
                                      {result.ml_enhanced.risk_score ?? '—'}
                                    </p>
                                  </div>
                                  <div className="p-2 rounded-lg bg-gray-50 dark:bg-gray-700/40">
                                    <p className="text-[10px] uppercase tracking-wider text-gray-400">Confidence</p>
                                    <p className="font-medium text-gray-900 dark:text-white">
                                      {Math.round((result.ml_enhanced.category_confidence || 0) * 100)}%
                                    </p>
                                  </div>
                                </div>
                                {result.ml_enhanced.vulnerabilities?.length > 0 && (
                                  <div className="flex flex-wrap gap-1">
                                    {result.ml_enhanced.vulnerabilities.map((vuln: string) => (
                                      <span
                                        key={vuln}
                                        className="text-[10px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
                                      >
                                        {vuln}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Security Vulnerabilities */}
                            {result.security?.vulnerabilities?.length > 0 && (
                              <div className="space-y-2 pt-2 border-t border-gray-100 dark:border-gray-700">
                                <div className="flex items-center gap-1.5">
                                  <Shield size={13} className="text-red-500" />
                                  <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                                    Unauthorized Access Vectors ({result.security.vulnerabilities.length})
                                  </span>
                                </div>
                                {result.security.vulnerabilities.map((vuln: any, idx: number) => {
                                  const SevIcon = SEVERITY_ICONS[vuln.severity] || Shield
                                  return (
                                    <div
                                      key={idx}
                                      className={`p-3 rounded-lg border text-xs ${SEVERITY_COLORS[vuln.severity] || 'bg-gray-50 text-gray-600'}`}
                                    >
                                      <div className="flex items-start gap-2">
                                        <SevIcon size={14} className="mt-0.5 flex-shrink-0" />
                                        <div className="space-y-1.5 min-w-0">
                                          <div className="flex items-center gap-1.5">
                                            <span className="font-semibold uppercase text-[10px]">{vuln.severity}</span>
                                            <span className="font-medium">{vuln.type}</span>
                                          </div>
                                          <p className="opacity-80 leading-relaxed">{vuln.description}</p>
                                          <div className="pt-1">
                                            <p className="font-medium text-[10px] uppercase tracking-wider opacity-60 mb-0.5">Attack Vector</p>
                                            <p className="opacity-80 leading-relaxed">{vuln.attack_vector}</p>
                                          </div>
                                          <div className="pt-0.5">
                                            <p className="font-medium text-[10px] uppercase tracking-wider opacity-60 mb-0.5">Exploit</p>
                                            <code className="block p-1.5 rounded bg-black/10 dark:bg-white/10 font-mono text-[11px] leading-relaxed break-all">
                                              {vuln.exploit_example}
                                            </code>
                                          </div>
                                        </div>
                                      </div>
                                    </div>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
