import { useState, useMemo, useEffect } from 'react'
import Header from './components/Header'
import PincodeInput from './components/PincodeInput'
import PlatformSelector from './components/PlatformSelector'
import CategorySelector from './components/CategorySelector'
import ProductTable from './components/ProductTable'
import ComparisonView from './components/ComparisonView'
import ExportButton from './components/ExportButton'
import LoadingSpinner from './components/LoadingSpinner'
import ErrorBanner from './components/ErrorBanner'
import { useScrapeData } from './hooks/useScrapeData'
import { PLATFORMS } from './utils/constants'

export default function App() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem('theme')
    return saved ? saved === 'dark' : true
  })
  const [selectedPincodes, setSelectedPincodes] = useState([])
  const [selectedPlatforms, setSelectedPlatforms] = useState(['blinkit', 'zepto', 'instamart', 'jiomart', 'flipkart_minutes'])
  const [selectedCategories, setSelectedCategories] = useState({})
  const [view, setView] = useState('table')
  const { data, loading, error, scrape, platformProgress } = useScrapeData()

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  const allProducts = useMemo(() => data?.results ? data.results.flatMap(r => r.products || []) : [], [data])

  const handleFetch = () => {
    if (selectedPincodes.length === 0 || selectedPlatforms.length === 0) return
    scrape(selectedPincodes, selectedPlatforms, selectedCategories)
  }

  const isValid = selectedPincodes.length > 0 && selectedPlatforms.length > 0

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-200 transition-colors">
      <Header dark={dark} onToggleTheme={() => setDark(d => !d)} />

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* Input Card */}
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 space-y-6 shadow-sm dark:shadow-none">
          <PincodeInput pincodes={selectedPincodes} onPincodesChange={setSelectedPincodes} />
          <div className="border-t border-gray-200 dark:border-gray-800 pt-5">
            <PlatformSelector selected={selectedPlatforms} onChange={setSelectedPlatforms} />
          </div>
          {selectedPlatforms.length > 0 && (
            <div className="border-t border-gray-200 dark:border-gray-800 pt-5">
              <CategorySelector
                selectedPlatforms={selectedPlatforms}
                selectedCategories={selectedCategories}
                onChange={setSelectedCategories}
              />
            </div>
          )}
          <div className="border-t border-gray-200 dark:border-gray-800 pt-5 flex flex-wrap items-center gap-4">
            <button onClick={handleFetch} disabled={!isValid || loading}
              className="flex items-center gap-2 px-8 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-purple-600 dark:to-indigo-600 text-white rounded-xl text-sm font-bold hover:from-blue-500 hover:to-indigo-500 dark:hover:from-purple-500 dark:hover:to-indigo-500 disabled:opacity-30 disabled:cursor-not-allowed transition-all shadow-lg shadow-blue-600/20 dark:shadow-purple-600/20 hover:shadow-xl hover:shadow-blue-600/30 dark:hover:shadow-purple-600/30">
              {loading ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>
                  Scraping {selectedPincodes.length} &times; {selectedPlatforms.length}...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
                  Fetch Data
                  {selectedPincodes.length > 0 && <span className="bg-white/20 px-2 py-0.5 rounded-md text-xs">{selectedPincodes.length} &times; {selectedPlatforms.length}</span>}
                </>
              )}
            </button>
            <ExportButton products={allProducts} pincode={selectedPincodes.join(',')} platforms={selectedPlatforms} disabled={loading} />
            {selectedPincodes.length === 0 && <span className="text-sm text-red-500 dark:text-red-400 font-medium">Select at least one pincode</span>}
            {selectedPlatforms.length === 0 && <span className="text-sm text-red-500 dark:text-red-400 font-medium">Select at least one platform</span>}
          </div>
        </div>

        {error && <ErrorBanner message={error} type="error" />}
        {data?.results?.filter(r => r.status === 'failed').map((r, i) => (
          <ErrorBanner key={`${r.platform}-${r.pincode}-${i}`} type="warning"
            message={`${PLATFORMS.find(p => p.id === r.platform)?.name || r.platform} (${r.pincode}): ${r.error_message || 'Not available'}`} />
        ))}

        {loading && (
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800">
            <LoadingSpinner platforms={selectedPlatforms} platformProgress={platformProgress} />
          </div>
        )}

        {!loading && data && (
          <>
            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {[...new Set(data.results?.map(r => r.platform))].map(platform => {
                const pl = PLATFORMS.find(p => p.id === platform)
                const results = data.results.filter(r => r.platform === platform)
                const total = results.reduce((s, r) => s + r.total_products, 0)
                const avgDur = (results.reduce((s, r) => s + r.scrape_duration_seconds, 0) / results.length).toFixed(1)
                const allFailed = results.every(r => r.status === 'failed')
                const hasPartialZero = !allFailed && total === 0
                const failedResult = results.find(r => r.status === 'failed')
                return (
                  <div key={platform} className={`bg-white dark:bg-gray-900 rounded-xl border p-3.5 shadow-sm dark:shadow-none ${
                    allFailed ? 'border-red-200 dark:border-red-900/50' :
                    hasPartialZero ? 'border-amber-200 dark:border-amber-900/50' :
                    'border-gray-200 dark:border-gray-800'
                  }`}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="w-3 h-3 rounded-full" style={{ backgroundColor: pl?.color }}></span>
                      <span className="text-xs font-bold text-gray-600 dark:text-gray-300 truncate">{pl?.name}</span>
                    </div>
                    {allFailed ? (
                      <>
                        <p className="text-sm font-bold text-red-500 dark:text-red-400">Failed</p>
                        {failedResult?.error_message && (
                          <p className="text-xs text-red-400 dark:text-red-500 truncate mt-0.5" title={failedResult.error_message}>
                            {failedResult.error_message.substring(0, 50)}{failedResult.error_message.length > 50 ? '...' : ''}
                          </p>
                        )}
                      </>
                    ) : hasPartialZero ? (
                      <>
                        <p className="text-xl font-bold text-amber-600 dark:text-amber-400">0</p>
                        <p className="text-xs text-amber-500 dark:text-amber-500">products &bull; {avgDur}s</p>
                      </>
                    ) : (
                      <><p className="text-xl font-bold text-gray-900 dark:text-white">{total}</p><p className="text-xs text-gray-400 dark:text-gray-500">products &bull; {avgDur}s</p></>
                    )}
                  </div>
                )
              })}
              <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-3.5 shadow-sm dark:shadow-none">
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-3 h-3 rounded-full bg-blue-500 dark:bg-purple-500"></span>
                  <span className="text-xs font-bold text-gray-600 dark:text-gray-300">Total</span>
                </div>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{data.total_products}</p>
                <p className="text-xs text-gray-400 dark:text-gray-500">{data.total_duration_seconds}s &bull; {selectedPincodes.length} pin{selectedPincodes.length > 1 ? 's' : ''}</p>
              </div>
            </div>

            {/* View Toggle */}
            <div className="flex items-center gap-2 bg-gray-100 dark:bg-gray-800 rounded-xl p-1 w-fit">
              {['table', 'compare'].map(v => (
                <button key={v} onClick={() => setView(v)}
                  className={`px-5 py-2 rounded-lg text-sm font-medium transition-all ${view === v ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}>
                  {v === 'table' ? 'Product Table' : 'Price Comparison'}
                </button>
              ))}
            </div>

            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 shadow-sm dark:shadow-none">
              {view === 'table' ? <ProductTable data={data} selectedPlatforms={selectedPlatforms} /> : <ComparisonView data={data} selectedPlatforms={selectedPlatforms} />}
            </div>
          </>
        )}
      </main>

      <footer className="text-center py-6 text-xs text-gray-400 dark:text-gray-600">Price Benchmark v1.0 &mdash; Quick Commerce Assortment Tracker</footer>
    </div>
  )
}
