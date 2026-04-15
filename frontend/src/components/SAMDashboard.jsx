import { useState, useEffect, useRef, useCallback } from 'react'

// ─── Constants ────────────────────────────────────────────────────────────────

const STAGE_COLORS = {
  'Stage 1 (PDP)': '#3B82F6',
  'Stage 2 (Brand)': '#10B981',
  'Stage 3 (Type/MRP)': '#F59E0B',
  'Stage 4 (Search)': '#8B5CF6',
  'Stage 5 (Image/Barcode)': '#EF4444',
}

const PLATFORM_META = {
  blinkit: { label: 'Blinkit', color: '#F8C723', darkColor: '#FCD34D' },
  jiomart: { label: 'JioMart', color: '#0078AD', darkColor: '#38BDF8' },
}

const CITY_LIST = [
  { pincode: '834002', name: 'Ranchi' },
  { pincode: '712232', name: 'Kolkata' },
  { pincode: '492001', name: 'Raipur' },
  { pincode: '825301', name: 'Hazaribagh' },
]

const PLATFORM_LIST = ['blinkit', 'jiomart']

// ─── Utility: coverage color class ───────────────────────────────────────────

function coverageColor(pct) {
  if (pct >= 90) return 'text-green-400'
  if (pct >= 70) return 'text-yellow-400'
  return 'text-red-400'
}

function coverageBg(pct) {
  if (pct >= 90) return 'bg-green-500'
  if (pct >= 70) return 'bg-yellow-500'
  return 'bg-red-500'
}

function coverageBadge(pct) {
  if (pct >= 90) return 'bg-green-500/10 text-green-400 ring-green-500/20'
  if (pct >= 70) return 'bg-yellow-500/10 text-yellow-400 ring-yellow-500/20'
  return 'bg-red-500/10 text-red-400 ring-red-500/20'
}

// ─── Shared spinner SVG ──────────────────────────────────────────────────────

function Spinner({ className = 'w-4 h-4' }) {
  return (
    <svg className={`${className} animate-spin`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

// ─── Icons (inline SVG) ──────────────────────────────────────────────────────

function IconDownload({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
    </svg>
  )
}

function IconRefresh({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
    </svg>
  )
}

function IconPlay({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function IconClock({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function IconCheck({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  )
}

function IconChart({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    </svg>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function CoverageBar({ pct, height = 'h-2.5' }) {
  return (
    <div className="flex items-center gap-2 w-full">
      <div className={`flex-1 ${height} bg-gray-800 rounded-full overflow-hidden`}>
        <div
          className={`h-full ${coverageBg(pct)} rounded-full transition-all duration-700 ease-out`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <span className={`text-xs font-bold tabular-nums w-12 text-right ${coverageColor(pct)}`}>
        {pct}%
      </span>
    </div>
  )
}

function StageBreakdown({ stages }) {
  const total = Object.values(stages).reduce((s, v) => s + v, 0)
  if (total === 0) return <span className="text-xs text-gray-500">No stage data</span>
  return (
    <div className="flex h-3 rounded-full overflow-hidden bg-gray-800">
      {Object.entries(stages).map(([name, count]) => {
        if (count === 0) return null
        const pct = (count / total) * 100
        return (
          <div
            key={name}
            className="relative group transition-all duration-500"
            style={{ width: `${pct}%`, backgroundColor: STAGE_COLORS[name] || '#6B7280' }}
          >
            <div className="absolute bottom-5 left-1/2 -translate-x-1/2 bg-gray-950 text-gray-200 text-[10px] px-2 py-1 rounded-md opacity-0 group-hover:opacity-100 whitespace-nowrap z-20 pointer-events-none border border-gray-700 shadow-lg">
              {name}: {count} ({pct.toFixed(1)}%)
            </div>
          </div>
        )
      })}
    </div>
  )
}

function DownloadButton({ pincode, city, variant = 'small' }) {
  const [downloading, setDownloading] = useState(false)

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const res = await fetch(`/api/sam/download/${pincode}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `SAM_${city}_${pincode}_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert(`Download failed: ${e.message}`)
    }
    setDownloading(false)
  }

  if (variant === 'small') {
    return (
      <button
        onClick={handleDownload}
        disabled={downloading}
        className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded-md bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors disabled:opacity-40"
        title={`Download ${city} CSV`}
      >
        {downloading ? <Spinner className="w-3 h-3" /> : <IconDownload className="w-3 h-3" />}
        CSV
      </button>
    )
  }

  return (
    <button
      onClick={handleDownload}
      disabled={downloading}
      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-700 hover:bg-gray-800 text-gray-300 transition-colors disabled:opacity-40"
    >
      {downloading ? <Spinner className="w-3.5 h-3.5" /> : <IconDownload className="w-3.5 h-3.5" />}
      Download CSV
    </button>
  )
}

function DownloadAllButton() {
  const [downloading, setDownloading] = useState(false)

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const res = await fetch('/api/sam/download/all')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `SAM_All_Cities_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert(`Download failed: ${e.message}`)
    }
    setDownloading(false)
  }

  return (
    <button
      onClick={handleDownload}
      disabled={downloading}
      className="flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-xl bg-white/10 hover:bg-white/20 backdrop-blur text-white transition-all disabled:opacity-40"
    >
      {downloading ? <Spinner className="w-4 h-4" /> : <IconDownload className="w-4 h-4" />}
      Download All CSV
    </button>
  )
}

// ─── Checkbox components ─────────────────────────────────────────────────────

function Checkbox({ checked, onChange, label, sublabel, color }) {
  return (
    <label className="flex items-center gap-2.5 cursor-pointer group select-none">
      <div className="relative flex items-center justify-center">
        <input
          type="checkbox"
          checked={checked}
          onChange={onChange}
          className="sr-only peer"
        />
        <div
          className={`w-4.5 h-4.5 w-[18px] h-[18px] rounded-md border-2 transition-all peer-focus-visible:ring-2 ring-offset-1 ring-offset-gray-900 ${
            checked
              ? 'border-transparent'
              : 'border-gray-600 group-hover:border-gray-400'
          }`}
          style={checked ? { backgroundColor: color || '#8B5CF6' } : {}}
        >
          {checked && (
            <svg className="w-full h-full text-white p-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        {color && <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />}
        <span className="text-sm font-medium text-gray-200 group-hover:text-white transition-colors">{label}</span>
        {sublabel && <span className="text-[10px] text-gray-500">{sublabel}</span>}
      </div>
    </label>
  )
}

// ─── Pipeline Log ────────────────────────────────────────────────────────────

function PipelineLog({ logs }) {
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  if (!logs || logs.length === 0) return null

  return (
    <div
      ref={scrollRef}
      className="mt-3 max-h-40 overflow-y-auto rounded-lg bg-gray-950 border border-gray-800 p-3 font-mono text-[11px] leading-relaxed text-gray-400 scrollbar-thin"
    >
      {logs.map((entry, i) => (
        <div key={i} className="flex gap-2">
          <span className="text-gray-600 shrink-0">[{entry.time}]</span>
          <span className={
            entry.msg.includes('Error') || entry.msg.includes('error')
              ? 'text-red-400'
              : entry.msg.includes('Done') || entry.msg.includes('complete')
              ? 'text-green-400'
              : 'text-gray-300'
          }>{entry.msg}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Status Pill ─────────────────────────────────────────────────────────────

function StatusPill({ running, lastResult, completedAt }) {
  if (running) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-full bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/20">
        <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
        Running
      </span>
    )
  }
  if (lastResult === 'success') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-full bg-green-500/10 text-green-400 ring-1 ring-inset ring-green-500/20">
        <IconCheck className="w-3 h-3" />
        Complete
      </span>
    )
  }
  if (lastResult && lastResult.startsWith('error')) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-full bg-red-500/10 text-red-400 ring-1 ring-inset ring-red-500/20">
        Failed
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-full bg-gray-500/10 text-gray-400 ring-1 ring-inset ring-gray-500/20">
      Idle
    </span>
  )
}

// ─── Stat Card ───────────────────────────────────────────────────────────────

function StatCard({ label, value, icon, sub }) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 flex items-start gap-3">
      <div className="p-2 rounded-lg bg-gray-800 text-gray-400 shrink-0">
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-2xl font-bold text-white tabular-nums leading-none">{value}</p>
        <p className="text-xs text-gray-500 mt-1">{label}</p>
        {sub && <p className="text-[10px] text-gray-600 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function SAMDashboard() {
  // Dashboard data
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  // Pipeline controls
  const [selectedCities, setSelectedCities] = useState(CITY_LIST.map(c => c.pincode))
  const [selectedPlatforms, setSelectedPlatforms] = useState([...PLATFORM_LIST])
  const [pipelineStatus, setPipelineStatus] = useState({
    running: false, progress: [], started_at: null, completed_at: null, last_result: null, config: {},
  })

  // Schedule
  const [schedule, setSchedule] = useState({
    enabled: false, time: '10:30', cities: CITY_LIST.map(c => c.pincode), platforms: [...PLATFORM_LIST],
  })
  const [savingSchedule, setSavingSchedule] = useState(false)

  // Polling ref
  const pollRef = useRef(null)

  // ─── Fetch dashboard data ──────────────────────────────────────────────────

  const fetchData = useCallback(() => {
    setLoading(true)
    setError(null)
    fetch('/api/sam/dashboard')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => {
        setData(d)
        setLastUpdated(new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }))
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  // ─── Fetch pipeline status ─────────────────────────────────────────────────

  const fetchPipelineStatus = useCallback(() => {
    fetch('/api/pipeline/status')
      .then(r => r.json())
      .then(d => {
        setPipelineStatus(d)
        // If pipeline just finished, refresh dashboard data
        if (!d.running && pipelineStatus.running) {
          fetchData()
        }
      })
      .catch(() => {})
  }, [pipelineStatus.running, fetchData])

  // ─── Fetch schedule ────────────────────────────────────────────────────────

  const fetchSchedule = useCallback(() => {
    fetch('/api/pipeline/schedule')
      .then(r => r.json())
      .then(d => setSchedule(d))
      .catch(() => {})
  }, [])

  // ─── Initial load ──────────────────────────────────────────────────────────

  useEffect(() => {
    fetchData()
    fetchPipelineStatus()
    fetchSchedule()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Poll pipeline status when running ─────────────────────────────────────

  useEffect(() => {
    if (pipelineStatus.running) {
      pollRef.current = setInterval(fetchPipelineStatus, 3000)
    } else {
      if (pollRef.current) clearInterval(pollRef.current)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [pipelineStatus.running, fetchPipelineStatus])

  // ─── Run pipeline ──────────────────────────────────────────────────────────

  const handleRunPipeline = async () => {
    if (selectedCities.length === 0 || selectedPlatforms.length === 0) return
    try {
      const res = await fetch('/api/pipeline/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cities: selectedCities, platforms: selectedPlatforms }),
      })
      const d = await res.json()
      if (d.status === 'started') {
        setPipelineStatus(prev => ({ ...prev, running: true, progress: [], last_result: null }))
      }
    } catch (e) {
      alert(`Failed to start pipeline: ${e.message}`)
    }
  }

  // ─── Save schedule ─────────────────────────────────────────────────────────

  const handleSaveSchedule = async (updates) => {
    setSavingSchedule(true)
    const newSchedule = { ...schedule, ...updates }
    try {
      const res = await fetch('/api/pipeline/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSchedule),
      })
      const d = await res.json()
      if (d.schedule) setSchedule(d.schedule)
    } catch (e) {
      alert(`Failed to update schedule: ${e.message}`)
    }
    setSavingSchedule(false)
  }

  // ─── Toggle helpers ────────────────────────────────────────────────────────

  const toggleCity = (pin) => {
    setSelectedCities(prev =>
      prev.includes(pin) ? prev.filter(p => p !== pin) : [...prev, pin]
    )
  }

  const togglePlatform = (plat) => {
    setSelectedPlatforms(prev =>
      prev.includes(plat) ? prev.filter(p => p !== plat) : [...prev, plat]
    )
  }

  // ─── Compute stats from data ───────────────────────────────────────────────

  const totalProducts = data ? data.grand_total.usable : 0
  const totalMatched = data ? data.grand_total.matched : 0
  const totalCities = data ? data.cities.length : 0
  const totalPlatforms = data ? [...new Set(data.results.map(r => r.platform))].length : 0
  const grandPct = data ? data.grand_total.coverage_pct : 0

  // Group results by city
  const citiesGrouped = {}
  if (data) {
    data.results.forEach(r => {
      if (!citiesGrouped[r.city]) citiesGrouped[r.city] = { pincode: r.pincode, platforms: {} }
      citiesGrouped[r.city].platforms[r.platform] = r
    })
  }

  // ─── Loading state ─────────────────────────────────────────────────────────

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner className="w-8 h-8 text-purple-500" />
        <span className="ml-3 text-gray-500">Loading SAM dashboard...</span>
      </div>
    )
  }

  // ─── Error state ───────────────────────────────────────────────────────────

  if (error && !data) {
    return (
      <div className="rounded-xl border border-red-800 bg-red-900/20 p-4 text-red-400 text-sm">
        Error loading dashboard: {error}. Make sure the backend is running.
        <button onClick={fetchData} className="ml-3 underline hover:text-red-300">Retry</button>
      </div>
    )
  }

  if (!data) return null

  // ─── Compute next scheduled run ────────────────────────────────────────────

  let nextRunLabel = null
  if (schedule.enabled && schedule.time) {
    const [hh, mm] = schedule.time.split(':').map(Number)
    const now = new Date()
    const next = new Date()
    next.setHours(hh, mm, 0, 0)
    if (next <= now) next.setDate(next.getDate() + 1)
    const diffMs = next - now
    const diffH = Math.floor(diffMs / 3600000)
    const diffM = Math.floor((diffMs % 3600000) / 60000)
    nextRunLabel = `in ${diffH}h ${diffM}m`
  }

  // ─── RENDER ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">

      {/* ═══ SECTION 1 + 2: Pipeline Controls + Schedule ═══════════════════ */}
      <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-bold text-gray-200 uppercase tracking-wider">Pipeline Controls</h2>
          <StatusPill
            running={pipelineStatus.running}
            lastResult={pipelineStatus.last_result}
            completedAt={pipelineStatus.completed_at}
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr_auto_auto] gap-5 items-start">
          {/* City selection */}
          <div>
            <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Cities</p>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {CITY_LIST.map(c => (
                <Checkbox
                  key={c.pincode}
                  checked={selectedCities.includes(c.pincode)}
                  onChange={() => toggleCity(c.pincode)}
                  label={c.name}
                  sublabel={c.pincode}
                  color="#8B5CF6"
                />
              ))}
            </div>
          </div>

          {/* Divider */}
          <div className="hidden md:block w-px h-14 bg-gray-800 self-center" />

          {/* Platform selection */}
          <div>
            <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Platforms</p>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {PLATFORM_LIST.map(plat => (
                <Checkbox
                  key={plat}
                  checked={selectedPlatforms.includes(plat)}
                  onChange={() => togglePlatform(plat)}
                  label={PLATFORM_META[plat].label}
                  color={PLATFORM_META[plat].color}
                />
              ))}
            </div>
          </div>

          {/* Divider */}
          <div className="hidden md:block w-px h-14 bg-gray-800 self-center" />

          {/* Schedule + Run button */}
          <div className="flex flex-col gap-3">
            {/* Run Pipeline button */}
            <button
              onClick={handleRunPipeline}
              disabled={pipelineStatus.running || selectedCities.length === 0 || selectedPlatforms.length === 0}
              className={`flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-bold rounded-xl transition-all shadow-lg ${
                pipelineStatus.running
                  ? 'bg-gray-700 text-gray-400 cursor-not-allowed shadow-none'
                  : 'bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:from-purple-500 hover:to-indigo-500 shadow-purple-600/25 hover:shadow-purple-600/40'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {pipelineStatus.running ? (
                <>
                  <Spinner className="w-4 h-4" />
                  Running...
                </>
              ) : (
                <>
                  <IconPlay className="w-4 h-4" />
                  Run Pipeline
                </>
              )}
            </button>

            {/* Schedule inline */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleSaveSchedule({ enabled: !schedule.enabled })}
                disabled={savingSchedule}
                className={`relative w-9 h-5 rounded-full transition-colors ${
                  schedule.enabled ? 'bg-purple-600' : 'bg-gray-700'
                }`}
              >
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                  schedule.enabled ? 'left-[18px]' : 'left-0.5'
                }`} />
              </button>
              <span className="text-xs text-gray-400">Daily</span>
              <input
                type="time"
                value={schedule.time}
                onChange={(e) => handleSaveSchedule({ time: e.target.value })}
                className="bg-gray-800 border border-gray-700 rounded-md px-2 py-0.5 text-xs text-gray-300 w-[80px] focus:outline-none focus:ring-1 focus:ring-purple-500"
              />
            </div>

            {schedule.enabled && nextRunLabel && (
              <div className="flex items-center gap-1 text-[10px] text-gray-500">
                <IconClock className="w-3 h-3" />
                Next run {nextRunLabel}
              </div>
            )}
          </div>
        </div>

        {/* Pipeline progress log */}
        <PipelineLog logs={pipelineStatus.progress} />

        {pipelineStatus.completed_at && !pipelineStatus.running && (
          <p className="text-[10px] text-gray-600 mt-2">
            Last run completed: {new Date(pipelineStatus.completed_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}
          </p>
        )}
      </div>

      {/* ═══ SECTION 4: Stats Bar ═══════════════════════════════════════════ */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Products Tracked"
          value={totalProducts.toLocaleString()}
          icon={<IconChart className="w-5 h-5" />}
          sub={`${totalMatched.toLocaleString()} matched`}
        />
        <StatCard
          label="Cities"
          value={totalCities}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          }
          sub={data.cities.join(', ')}
        />
        <StatCard
          label="Platforms"
          value={totalPlatforms}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
          }
          sub="Blinkit + JioMart"
        />
        <StatCard
          label="Coverage"
          value={`${grandPct}%`}
          icon={<IconCheck className="w-5 h-5" />}
          sub={
            grandPct >= 90 ? 'Excellent' :
            grandPct >= 70 ? 'Good — room to improve' :
            'Needs attention'
          }
        />
      </div>

      {/* ═══ SECTION 3: Grand Total Card ═══════════════════════════════════ */}
      <div className="rounded-2xl bg-gradient-to-br from-purple-600 via-indigo-600 to-blue-600 p-5 text-white relative overflow-hidden">
        {/* Background decoration */}
        <div className="absolute top-0 right-0 w-40 h-40 bg-white/5 rounded-full -translate-y-10 translate-x-10" />
        <div className="absolute bottom-0 left-0 w-24 h-24 bg-white/5 rounded-full translate-y-8 -translate-x-8" />

        <div className="relative z-10 flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-white/60 uppercase tracking-wider">SAM Total Coverage</p>
            <div className="flex items-baseline gap-3 mt-1">
              <p className="text-5xl font-black tabular-nums">{grandPct}%</p>
              <span className={`text-sm font-semibold px-2 py-0.5 rounded-md ${
                grandPct >= 90 ? 'bg-green-400/20 text-green-200' :
                grandPct >= 70 ? 'bg-yellow-400/20 text-yellow-200' :
                'bg-red-400/20 text-red-200'
              }`}>
                {grandPct >= 90 ? 'Excellent' : grandPct >= 70 ? 'Good' : 'Low'}
              </span>
            </div>
            <p className="text-sm text-white/50 mt-1">
              {totalMatched.toLocaleString()} / {totalProducts.toLocaleString()} products matched
            </p>
            {lastUpdated && (
              <p className="text-[10px] text-white/30 mt-2">Updated: {lastUpdated}</p>
            )}
          </div>
          <div className="flex flex-col items-center gap-3">
            <div className="text-5xl">
              {grandPct >= 90 ? '\uD83D\uDE80' : grandPct >= 70 ? '\u26A1' : '\uD83D\uDD27'}
            </div>
            <DownloadAllButton />
          </div>
        </div>

        {/* Grand progress bar */}
        <div className="relative z-10 mt-4 h-3 bg-white/15 rounded-full overflow-hidden">
          <div
            className="h-full bg-white rounded-full transition-all duration-1000 ease-out"
            style={{ width: `${grandPct}%` }}
          />
        </div>
      </div>

      {/* ═══ SECTION 3 continued: City Breakdown Header ═════════════════════ */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-gray-200 uppercase tracking-wider">
          City Breakdown
        </h2>
        <button
          onClick={fetchData}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors disabled:opacity-40"
        >
          <IconRefresh className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* ═══ SECTION 3 continued: Per-City Cards ═══════════════════════════ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {Object.entries(citiesGrouped).map(([city, info]) => {
          // Compute city-level stats
          const cityUsable = Object.values(info.platforms).reduce((s, r) => s + r.usable, 0)
          const cityMatched = Object.values(info.platforms).reduce((s, r) => s + r.matched, 0)
          const cityPct = cityUsable > 0 ? Math.round(cityMatched * 100 / cityUsable * 10) / 10 : 0

          return (
            <div
              key={city}
              className="rounded-xl border border-gray-800 bg-gray-900/50 p-4 hover:border-gray-700 transition-colors"
            >
              {/* City header */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <h3 className="text-base font-bold text-white">{city}</h3>
                  <span className="text-[10px] text-gray-500 font-mono">{info.pincode}</span>
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-md ring-1 ring-inset ${coverageBadge(cityPct)}`}>
                    {cityPct}%
                  </span>
                </div>
                <DownloadButton pincode={info.pincode} city={city} variant="small" />
              </div>

              {/* Platform rows */}
              <div className="space-y-3">
                {PLATFORM_LIST.map(plat => {
                  const r = info.platforms[plat]

                  if (!r) {
                    return (
                      <div key={plat} className="flex items-center gap-3 opacity-30">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: PLATFORM_META[plat].color }} />
                        <span className="text-xs font-medium w-16 capitalize">{PLATFORM_META[plat].label}</span>
                        <span className="text-[10px] text-gray-600">Not available</span>
                      </div>
                    )
                  }

                  return (
                    <div key={plat} className="space-y-1.5">
                      {/* Platform header line */}
                      <div className="flex items-center gap-2">
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ backgroundColor: PLATFORM_META[plat].color }}
                        />
                        <span className="text-xs font-bold w-16" style={{ color: PLATFORM_META[plat].darkColor }}>
                          {PLATFORM_META[plat].label}
                        </span>
                        <span className="text-[10px] text-gray-500 tabular-nums">
                          {r.matched.toLocaleString()} / {r.usable.toLocaleString()}
                        </span>
                        {r.unmatched > 0 && (
                          <span className="text-[10px] text-gray-600 ml-auto">
                            {r.unmatched} unmatched
                          </span>
                        )}
                      </div>
                      {/* Coverage bar */}
                      <CoverageBar pct={r.coverage_pct} height="h-2" />
                      {/* Stage breakdown */}
                      <StageBreakdown stages={r.stages} />
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      {/* ═══ Stage Legend ═══════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-4 px-1">
        <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mr-1">Stages:</span>
        {Object.entries(STAGE_COLORS).map(([name, color]) => (
          <div key={name} className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: color }} />
            <span className="text-[10px] text-gray-500">{name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
