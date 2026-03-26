import { useMemo, useState } from 'react'
import { PLATFORMS } from '../utils/constants'

export default function ComparisonView({ data, selectedPlatforms }) {
  const [search, setSearch] = useState('')

  const compared = useMemo(() => {
    if (!data?.results) return []
    const map = {}
    for (const r of data.results) for (const p of r.products || []) {
      const key = p.product_name?.toLowerCase().replace(/\s+/g, ' ').trim()
      if (!key) continue
      if (!map[key]) map[key] = { product_name: p.product_name, brand: p.brand, unit: p.unit, category: p.category, prices: {} }
      map[key].prices[p.platform] = { price: p.price, mrp: p.mrp, in_stock: p.in_stock }
    }
    return Object.values(map).filter(p => Object.keys(p.prices).length >= 2).sort((a, b) => a.product_name.localeCompare(b.product_name))
  }, [data])

  const filtered = useMemo(() => {
    if (!search) return compared
    const q = search.toLowerCase()
    return compared.filter(p => p.product_name?.toLowerCase().includes(q) || p.brand?.toLowerCase().includes(q))
  }, [compared, search])

  const activePlatforms = PLATFORMS.filter(p => selectedPlatforms.includes(p.id))

  if (!compared.length) return (
    <div className="text-center py-12 text-gray-500 dark:text-gray-500">
      <p className="text-sm">No matching products across platforms.</p>
      <p className="text-xs mt-1 text-gray-400 dark:text-gray-600">Products need same name on 2+ platforms.</p>
    </div>
  )

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-xs">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          <input type="text" placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 pl-10 pr-3 py-2 text-sm text-gray-900 dark:text-gray-200 focus:ring-2 focus:ring-blue-500 dark:focus:ring-purple-500 placeholder-gray-400 dark:placeholder-gray-500" />
        </div>
        <span className="text-sm text-gray-500">{filtered.length} on 2+ platforms</span>
      </div>
      <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-800/80">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase">#</th>
              <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase">Product</th>
              <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase">Brand</th>
              <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase">Unit</th>
              {activePlatforms.map(p => <th key={p.id} className="px-4 py-3 text-center text-xs font-bold uppercase" style={{ color: p.color }}>{p.name}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {filtered.slice(0, 100).map((item, i) => {
              const prices = Object.values(item.prices).map(v => v.price).filter(p => p > 0)
              const min = Math.min(...prices)
              return (
                <tr key={i} className="hover:bg-blue-50/50 dark:hover:bg-gray-800/50">
                  <td className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">{i + 1}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 dark:text-gray-200 font-medium max-w-xs truncate">{item.product_name}</td>
                  <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">{item.brand}</td>
                  <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">{item.unit || '\u2014'}</td>
                  {activePlatforms.map(p => {
                    const info = item.prices[p.id]
                    if (!info) return <td key={p.id} className="px-4 py-3 text-center text-sm text-gray-300 dark:text-gray-600">&mdash;</td>
                    const best = info.price === min && info.price > 0
                    return (
                      <td key={p.id} className="px-4 py-3 text-center text-sm">
                        <span className={`font-bold ${best ? 'text-green-600 dark:text-emerald-400' : 'text-gray-900 dark:text-gray-300'}`}>
                          {info.price > 0 ? `\u20B9${info.price.toFixed(2)}` : '\u2014'}
                        </span>
                        {best && <span className="block text-xs text-green-500 dark:text-emerald-500">Lowest</span>}
                        {!info.in_stock && <span className="block text-xs text-red-500 dark:text-red-400">Out of stock</span>}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
