import { useState, useRef, useMemo } from 'react'
import { useCompare } from '../hooks/useCompare'
import { PLATFORMS } from '../utils/constants'

export default function DeltaCompare() {
  const [pincode, setPincode] = useState('')
  const [selectedPlatforms, setSelectedPlatforms] = useState(PLATFORMS.map(p => p.id))
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef(null)
  const { uploadInfo, uploading, comparing, progress, error, done, doneData, upload, startCompare, downloadResult, reset } = useCompare()

  const handleFile = async (file) => {
    if (!file) return
    if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.xls')) {
      alert('Please upload an Excel file (.xlsx)')
      return
    }
    await upload(file)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    handleFile(file)
  }

  const togglePlatform = (id) => {
    setSelectedPlatforms(prev =>
      prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]
    )
  }

  const handleStart = () => {
    if (!pincode.match(/^\d{6}$/)) {
      alert('Enter a valid 6-digit pincode')
      return
    }
    if (selectedPlatforms.length === 0) {
      alert('Select at least one platform')
      return
    }
    startCompare(pincode, selectedPlatforms)
  }

  // Aggregate progress from all platforms
  const agg = useMemo(() => {
    if (!progress?.byPlatform) return { current: 0, total: 0, pct: 0 }
    const entries = Object.values(progress.byPlatform)
    const current = entries.reduce((s, p) => s + (p.current || 0), 0)
    const total = entries.reduce((s, p) => s + (p.total || 0), 0)
    return { current, total, pct: total > 0 ? Math.round(current / total * 100) : 0 }
  }, [progress])

  // Currently searching product (from the platform with most recent activity)
  const lastProduct = useMemo(() => {
    if (!progress?.byPlatform) return ''
    const entries = Object.values(progress.byPlatform)
    let latest = ''
    let maxCurrent = 0
    for (const e of entries) {
      if ((e.current || 0) >= maxCurrent && e.product) {
        maxCurrent = e.current
        latest = e.product
      }
    }
    return latest
  }, [progress])

  return (
    <div className="space-y-6">
      {/* Upload Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Reference Excel</h3>
          {uploadInfo && (
            <button onClick={reset} className="text-xs text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300">
              Reset
            </button>
          )}
        </div>

        {!uploadInfo ? (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
              dragOver
                ? 'border-blue-500 dark:border-purple-500 bg-blue-50 dark:bg-purple-900/20'
                : 'border-gray-300 dark:border-gray-700 hover:border-blue-400 dark:hover:border-purple-500/50'
            }`}
          >
            <input ref={fileRef} type="file" accept=".xlsx,.xls" className="hidden" onChange={(e) => handleFile(e.target.files[0])} />
            {uploading ? (
              <div className="flex items-center justify-center gap-3">
                <svg className="w-5 h-5 animate-spin text-blue-600 dark:text-purple-400" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span className="text-sm text-gray-600 dark:text-gray-400">Parsing Excel...</span>
              </div>
            ) : (
              <>
                <svg className="w-10 h-10 mx-auto mb-3 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Drop your reference Excel here</p>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">or click to browse (.xlsx with &apos;anaken&apos; sheet)</p>
              </>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-4 p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl">
            <svg className="w-8 h-8 text-green-600 dark:text-green-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <p className="text-sm font-bold text-green-800 dark:text-green-300">{uploadInfo.filename}</p>
              <p className="text-xs text-green-600 dark:text-green-400">{uploadInfo.total} products detected</p>
            </div>
          </div>
        )}
      </div>

      {/* Platform Selector + Pincode + Start */}
      {uploadInfo && !comparing && !done && (
        <div className="space-y-4">
          {/* Platform checkboxes */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Platforms to Compare</label>
            <div className="flex flex-wrap gap-3">
              {PLATFORMS.map(p => (
                <label
                  key={p.id}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-all text-sm font-medium ${
                    selectedPlatforms.includes(p.id)
                      ? 'border-transparent shadow-sm'
                      : 'border-gray-200 dark:border-gray-700 opacity-40'
                  }`}
                  style={selectedPlatforms.includes(p.id) ? { backgroundColor: p.bg || '#f3f4f6', borderColor: p.color } : {}}
                >
                  <input
                    type="checkbox"
                    checked={selectedPlatforms.includes(p.id)}
                    onChange={() => togglePlatform(p.id)}
                    className="sr-only"
                  />
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: p.color }} />
                  <span className="text-gray-800 dark:text-gray-200">{p.name}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Pincode + Start */}
          <div className="flex items-end gap-4">
            <div>
              <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Pincode</label>
              <input
                type="text"
                value={pincode}
                onChange={(e) => setPincode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="e.g. 400001"
                className="w-40 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2.5 text-sm font-mono text-gray-900 dark:text-gray-200 focus:ring-2 focus:ring-blue-500 dark:focus:ring-purple-500 placeholder-gray-400 dark:placeholder-gray-500"
              />
            </div>
            <button
              onClick={handleStart}
              disabled={!pincode.match(/^\d{6}$/) || selectedPlatforms.length === 0}
              className="flex items-center gap-2 px-6 py-2.5 bg-gradient-to-r from-teal-600 to-cyan-600 dark:from-teal-500 dark:to-cyan-500 text-white rounded-xl text-sm font-bold hover:from-teal-500 hover:to-cyan-500 disabled:opacity-30 disabled:cursor-not-allowed transition-all shadow-lg shadow-teal-600/20"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              Compare on {selectedPlatforms.length} Platform{selectedPlatforms.length !== 1 ? 's' : ''}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
          <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
        </div>
      )}

      {/* Progress */}
      {(comparing || done) && progress && (
        <div className="space-y-4">
          {/* Overall progress bar */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                {done ? 'Comparison Complete' : 'Searching across platforms...'}
              </span>
              <span className="text-sm font-mono text-gray-500 dark:text-gray-400">
                {agg.current} / {agg.total}
              </span>
            </div>
            <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-3 overflow-hidden">
              <div
                className={`h-3 rounded-full transition-all duration-300 ${done ? 'bg-green-500' : 'bg-gradient-to-r from-teal-500 to-cyan-500'}`}
                style={{ width: `${agg.pct}%` }}
              />
            </div>
            {comparing && lastProduct && (
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1.5 truncate">
                Searching: {lastProduct}
              </p>
            )}
          </div>

          {/* Per-platform progress cards */}
          {progress.byPlatform && (
            <div className={`grid gap-3 ${Object.keys(progress.byPlatform).length <= 3 ? 'grid-cols-3' : 'grid-cols-2 md:grid-cols-5'}`}>
              {Object.entries(progress.byPlatform).map(([platId, pp]) => {
                const plat = PLATFORMS.find(p => p.id === platId)
                const matchRate = pp.total > 0 ? Math.round((pp.matched || 0) / pp.total * 100) : 0
                const platPct = pp.total > 0 ? ((pp.current || 0) / pp.total) * 100 : 0
                const isDone = (pp.current || 0) >= (pp.total || 0) && pp.total > 0

                return (
                  <div key={platId} className={`rounded-xl p-3 border transition-all ${
                    pp.error
                      ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                      : isDone
                        ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                        : 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700'
                  }`}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: plat?.color }} />
                      <span className="text-xs font-bold text-gray-700 dark:text-gray-300 truncate">{plat?.name || platId}</span>
                    </div>

                    {pp.error ? (
                      <p className="text-xs text-red-500 dark:text-red-400 truncate">{pp.error}</p>
                    ) : (
                      <>
                        <div className="flex items-baseline gap-1.5">
                          <span className="text-lg font-bold text-gray-900 dark:text-white">{pp.matched || 0}</span>
                          <span className="text-xs text-gray-400 dark:text-gray-500">/ {pp.total || 0}</span>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {matchRate}% matched
                        </p>
                        {/* Mini progress bar */}
                        <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 mt-2">
                          <div
                            className="h-1.5 rounded-full transition-all duration-300"
                            style={{
                              width: `${platPct}%`,
                              backgroundColor: plat?.color || '#6b7280',
                            }}
                          />
                        </div>
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* Done stats summary */}
          {done && doneData?.platforms && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="bg-gray-50 dark:bg-gray-800 rounded-xl p-3 border border-gray-200 dark:border-gray-700">
                <p className="text-xs text-gray-500 dark:text-gray-400 uppercase font-semibold">Products</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{progress.total || 0}</p>
              </div>
              <div className="bg-gray-50 dark:bg-gray-800 rounded-xl p-3 border border-gray-200 dark:border-gray-700">
                <p className="text-xs text-gray-500 dark:text-gray-400 uppercase font-semibold">Platforms</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{Object.keys(doneData.platforms).length}</p>
              </div>
              <div className="bg-green-50 dark:bg-green-900/20 rounded-xl p-3 border border-green-200 dark:border-green-800">
                <p className="text-xs text-green-600 dark:text-green-400 uppercase font-semibold">Best Match Rate</p>
                <p className="text-xl font-bold text-green-700 dark:text-green-300">
                  {Math.max(...Object.values(doneData.platforms).map(p => progress.total > 0 ? Math.round((p.matched || 0) / progress.total * 100) : 0))}%
                </p>
              </div>
              <div className="bg-blue-50 dark:bg-blue-900/20 rounded-xl p-3 border border-blue-200 dark:border-blue-800">
                <p className="text-xs text-blue-600 dark:text-blue-400 uppercase font-semibold">Total Matched</p>
                <p className="text-xl font-bold text-blue-700 dark:text-blue-300">
                  {Math.max(...Object.values(doneData.platforms).map(p => p.matched || 0))}
                </p>
              </div>
            </div>
          )}

          {/* Download */}
          {done && (
            <button
              onClick={downloadResult}
              className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-green-600 to-emerald-600 dark:from-green-500 dark:to-emerald-500 text-white rounded-xl text-sm font-bold hover:from-green-500 hover:to-emerald-500 transition-all shadow-lg shadow-green-600/20"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download Delta Excel
            </button>
          )}
        </div>
      )}
    </div>
  )
}
