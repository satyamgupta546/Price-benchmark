import { useState, useMemo } from 'react'
import { PLATFORMS } from '../utils/constants'

const PAGE_SIZE = 25

export default function ProductTable({ data, selectedPlatforms }) {
  const [search, setSearch] = useState('')
  const [brandFilter, setBrandFilter] = useState('')
  const [pincodeFilter, setPincodeFilter] = useState('')
  const [activeTab, setActiveTab] = useState('all')
  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('asc')
  const [page, setPage] = useState(1)

  const allProducts = useMemo(() => data?.results ? data.results.flatMap(r => r.products || []) : [], [data])
  const brands = useMemo(() => [...new Set(allProducts.map(p => p.brand).filter(Boolean))].sort(), [allProducts])
  const pincodesList = useMemo(() => [...new Set(allProducts.map(p => p.pincode).filter(Boolean))].sort(), [allProducts])

  const filtered = useMemo(() => {
    let items = allProducts
    if (activeTab !== 'all') items = items.filter(p => p.platform === activeTab)
    if (search) { const q = search.toLowerCase(); items = items.filter(p => p.product_name?.toLowerCase().includes(q) || p.brand?.toLowerCase().includes(q)) }
    if (brandFilter) items = items.filter(p => p.brand === brandFilter)
    if (pincodeFilter) items = items.filter(p => p.pincode === pincodeFilter)
    if (sortCol) {
      items = [...items].sort((a, b) => {
        let va = a[sortCol] ?? '', vb = b[sortCol] ?? ''
        if (typeof va === 'number' && typeof vb === 'number') return sortDir === 'asc' ? va - vb : vb - va
        return sortDir === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va))
      })
    }
    return items
  }, [allProducts, activeTab, search, brandFilter, pincodeFilter, sortCol, sortDir])

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const handleSort = (col) => { if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc'); else { setSortCol(col); setSortDir('asc') }; setPage(1) }

  const tabs = [
    { id: 'all', label: 'All', count: allProducts.length },
    ...selectedPlatforms.map(pid => {
      const p = PLATFORMS.find(pl => pl.id === pid)
      return { id: pid, label: p?.name || pid, count: allProducts.filter(pr => pr.platform === pid).length, color: p?.color }
    }),
  ]

  if (!data) {
    return (
      <div className="text-center py-20">
        <svg className="w-20 h-20 mx-auto mb-4 text-gray-300 dark:text-gray-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
        <p className="text-lg font-semibold text-gray-500 dark:text-gray-400">No data yet</p>
        <p className="text-sm mt-1 text-gray-400 dark:text-gray-500">Enter a pincode and click "Fetch Data" to get started</p>
      </div>
    )
  }

  if (allProducts.length === 0) {
    const results = data.results || []
    return (
      <div className="text-center py-16">
        <svg className="w-16 h-16 mx-auto mb-4 text-amber-400 dark:text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        <p className="text-lg font-semibold text-gray-700 dark:text-gray-300">Scrape completed, but no products were found</p>
        <p className="text-sm mt-1 text-gray-500 dark:text-gray-400 mb-4">The selected platforms didn't return any products for this pincode</p>
        {results.length > 0 && (
          <div className="max-w-md mx-auto text-left space-y-2 mb-6">
            {results.map((r, i) => {
              const pl = PLATFORMS.find(p => p.id === r.platform)
              const failed = r.status === 'failed'
              const zeroProducts = r.total_products === 0 && !failed
              return (
                <div key={`${r.platform}-${r.pincode}-${i}`} className="flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-800">
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: pl?.color || '#6b7280' }}></span>
                  <span className="font-medium text-gray-700 dark:text-gray-300">{pl?.name || r.platform}</span>
                  <span className="ml-auto text-xs">
                    {failed && <span className="text-red-500 dark:text-red-400">Failed{r.error_message ? `: ${r.error_message.substring(0, 60)}` : ''}</span>}
                    {zeroProducts && <span className="text-amber-600 dark:text-amber-400">0 products</span>}
                    {!failed && !zeroProducts && <span className="text-gray-400">{r.total_products} products</span>}
                  </span>
                </div>
              )
            })}
          </div>
        )}
        <p className="text-xs text-gray-400 dark:text-gray-500">Try a different pincode or check if these platforms deliver to the selected area</p>
      </div>
    )
  }

  const SortIcon = ({ col }) => {
    if (sortCol !== col) return <span className="text-gray-400 dark:text-gray-600 ml-1 text-xs">&uarr;&darr;</span>
    return <span className="text-blue-600 dark:text-purple-400 ml-1">{sortDir === 'asc' ? '\u2191' : '\u2193'}</span>
  }

  const thCls = "px-4 py-3.5 text-left text-xs font-bold text-gray-500 dark:text-gray-500 uppercase"
  const selectCls = "rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-200 focus:ring-2 focus:ring-blue-500 dark:focus:ring-purple-500"

  return (
    <div>
      {/* Tabs */}
      <div className="flex gap-1 mb-5 bg-gray-100 dark:bg-gray-800 rounded-xl p-1 overflow-x-auto">
        {tabs.map(tab => (
          <button key={tab.id} onClick={() => { setActiveTab(tab.id); setPage(1) }}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap ${activeTab === tab.id ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}>
            {tab.color && <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: tab.color }}></span>}
            {tab.label}
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${activeTab === tab.id ? 'bg-blue-100 dark:bg-purple-900/50 text-blue-700 dark:text-purple-300' : 'bg-gray-200 dark:bg-gray-700 text-gray-500'}`}>{tab.count}</span>
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          <input type="text" placeholder="Search products..." value={search} onChange={e => { setSearch(e.target.value); setPage(1) }}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 pl-10 pr-3 py-2 text-sm text-gray-900 dark:text-gray-200 focus:ring-2 focus:ring-blue-500 dark:focus:ring-purple-500 placeholder-gray-400 dark:placeholder-gray-500" />
        </div>
        <select value={brandFilter} onChange={e => { setBrandFilter(e.target.value); setPage(1) }} className={selectCls}>
          <option value="">All Brands</option>
          {brands.map(b => <option key={b} value={b}>{b}</option>)}
        </select>
        {pincodesList.length > 1 && (
          <select value={pincodeFilter} onChange={e => { setPincodeFilter(e.target.value); setPage(1) }} className={`${selectCls} font-mono`}>
            <option value="">All Pincodes</option>
            {pincodesList.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        )}
        <span className="text-sm text-gray-500 self-center ml-auto">{filtered.length} product{filtered.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-800/80">
            <tr>
              <th className={`${thCls} w-12`}>#</th>
              <th className={`${thCls} cursor-pointer hover:text-gray-700 dark:hover:text-gray-300`} onClick={() => handleSort('product_name')}>Product <SortIcon col="product_name" /></th>
              <th className={`${thCls} cursor-pointer hover:text-gray-700 dark:hover:text-gray-300`} onClick={() => handleSort('brand')}>Brand <SortIcon col="brand" /></th>
              <th className={`${thCls} cursor-pointer hover:text-gray-700 dark:hover:text-gray-300`} onClick={() => handleSort('price')}>Price <SortIcon col="price" /></th>
              <th className={thCls}>MRP</th>
              <th className={thCls}>Unit</th>
              <th className={`${thCls} cursor-pointer hover:text-gray-700 dark:hover:text-gray-300`} onClick={() => handleSort('category')}>Category <SortIcon col="category" /></th>
              <th className={thCls}>Platform</th>
              <th className={thCls}>Pincode</th>
              <th className={`${thCls} text-center`}>Stock</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {pageItems.map((p, i) => {
              const pl = PLATFORMS.find(x => x.id === p.platform)
              return (
                <tr key={`${p.platform}-${p.product_name}-${i}`} className="hover:bg-blue-50/50 dark:hover:bg-gray-800/50 transition-colors">
                  <td className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">{(page - 1) * PAGE_SIZE + i + 1}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 dark:text-gray-200 font-medium max-w-[250px] truncate">{p.product_name}</td>
                  <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">{p.brand}</td>
                  <td className="px-4 py-3 text-sm text-green-700 dark:text-emerald-400 font-bold tabular-nums">{p.price > 0 ? `\u20B9${p.price.toFixed(2)}` : '\u2014'}</td>
                  <td className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500 line-through tabular-nums">{p.mrp ? `\u20B9${p.mrp.toFixed(2)}` : ''}</td>
                  <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">{p.unit || '\u2014'}</td>
                  <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">{p.category || '\u2014'}</td>
                  <td className="px-4 py-3">
                    <span className="inline-block px-2.5 py-1 rounded-lg text-xs font-semibold border"
                      style={{ borderColor: (pl?.color || '#6b7280') + '40', color: pl?.color || '#6b7280', backgroundColor: (pl?.color || '#6b7280') + '15' }}>
                      {pl?.name || p.platform}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400 font-mono">{p.pincode}</td>
                  <td className="px-4 py-3 text-center">
                    {p.in_stock
                      ? <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-emerald-400"><span className="w-2 h-2 rounded-full bg-green-500 dark:bg-emerald-400"></span>Yes</span>
                      : <span className="inline-flex items-center gap-1 text-xs text-red-500 dark:text-red-400"><span className="w-2 h-2 rounded-full bg-red-500 dark:bg-red-400"></span>No</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4 px-1">
          <p className="text-sm text-gray-500">Showing {(page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}</p>
          <div className="flex gap-1">
            {[
              { label: '\u00AB', go: () => setPage(1), dis: page === 1 },
              { label: '\u2039', go: () => setPage(p => Math.max(1, p - 1)), dis: page === 1 },
              { label: `${page} / ${totalPages}`, go: null },
              { label: '\u203A', go: () => setPage(p => Math.min(totalPages, p + 1)), dis: page === totalPages },
              { label: '\u00BB', go: () => setPage(totalPages), dis: page === totalPages },
            ].map((b, i) => b.go ? (
              <button key={i} onClick={b.go} disabled={b.dis} className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-gray-800">{b.label}</button>
            ) : (
              <span key={i} className="px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300">{b.label}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
