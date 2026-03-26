import { useState, useEffect, useRef } from 'react'
import { PLATFORMS, API_BASE } from '../utils/constants'

export default function CategorySelector({ selectedPlatforms, selectedCategories, onChange }) {
  const [categoryOptions, setCategoryOptions] = useState({})
  const [loadingPlatforms, setLoadingPlatforms] = useState({})
  const [openDropdown, setOpenDropdown] = useState(null)

  useEffect(() => {
    for (const platform of selectedPlatforms) {
      if (categoryOptions[platform]) continue
      setLoadingPlatforms(prev => ({ ...prev, [platform]: true }))
      fetch(`${API_BASE}/categories/${platform}`)
        .then(res => res.json())
        .then(data => {
          if (data.categories) {
            setCategoryOptions(prev => ({ ...prev, [platform]: data.categories }))
          }
        })
        .catch(() => {})
        .finally(() => setLoadingPlatforms(prev => ({ ...prev, [platform]: false })))
    }
  }, [selectedPlatforms])

  const toggleCategory = (platform, category) => {
    const current = selectedCategories[platform] || ['all']
    let next

    if (category === 'all') {
      next = ['all']
    } else if (current.includes('all')) {
      next = [category]
    } else if (current.includes(category)) {
      next = current.filter(c => c !== category)
      if (next.length === 0) next = ['all']
    } else {
      next = [...current, category]
    }

    onChange({ ...selectedCategories, [platform]: next })
  }

  const getLabel = (platform) => {
    const selected = selectedCategories[platform] || ['all']
    if (selected.includes('all')) return 'All Categories'
    if (selected.length === 1) return selected[0]
    return `${selected[0]} +${selected.length - 1} more`
  }

  if (!selectedPlatforms.some(p => categoryOptions[p]?.length > 0 || loadingPlatforms[p])) {
    return null
  }

  return (
    <div>
      <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">Categories</label>
      <div className="flex flex-wrap gap-3">
        {selectedPlatforms.map(platform => {
          const pl = PLATFORMS.find(p => p.id === platform)
          const cats = categoryOptions[platform]
          const isLoading = loadingPlatforms[platform]
          const selected = selectedCategories[platform] || ['all']
          const isAll = selected.includes('all')
          const isOpen = openDropdown === platform

          if (!cats && !isLoading) return null

          return (
            <DropdownItem
              key={platform}
              platform={platform}
              pl={pl}
              cats={cats}
              isLoading={isLoading}
              selected={selected}
              isAll={isAll}
              isOpen={isOpen}
              label={getLabel(platform)}
              onToggleOpen={() => setOpenDropdown(isOpen ? null : platform)}
              onClose={() => setOpenDropdown(null)}
              onToggleCategory={(cat) => toggleCategory(platform, cat)}
            />
          )
        })}
      </div>
    </div>
  )
}

function DropdownItem({ platform, pl, cats, isLoading, selected, isAll, isOpen, label, onToggleOpen, onClose, onToggleCategory }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!isOpen) return
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [isOpen, onClose])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={onToggleOpen}
        className="flex items-center gap-2 px-3.5 py-2 rounded-xl border text-sm font-medium transition-all hover:shadow-md"
        style={{
          borderColor: pl?.color + '50',
          backgroundColor: pl?.color + '10',
        }}
      >
        <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: pl?.color }} />
        <span className="font-semibold text-gray-700 dark:text-gray-200 text-xs">{pl?.name}</span>
        <span className="text-gray-400 dark:text-gray-500 mx-0.5">|</span>
        <span className="text-xs truncate max-w-[160px]" style={{ color: isAll ? undefined : pl?.color }}>
          {isLoading ? 'Loading...' : label}
        </span>
        {!isAll && !isLoading && (
          <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 min-w-[18px] text-center text-white" style={{ backgroundColor: pl?.color }}>
            {selected.length}
          </span>
        )}
        <svg className={`w-3.5 h-3.5 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && cats && (
        <div className="absolute top-full left-0 mt-2 z-50 w-64 max-h-72 overflow-y-auto rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-xl shadow-black/10 dark:shadow-black/30">
          {/* All option */}
          <button
            onClick={() => onToggleCategory('all')}
            className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 text-xs font-semibold transition-colors border-b border-gray-100 dark:border-gray-700 ${
              isAll ? 'bg-gray-50 dark:bg-gray-750' : 'hover:bg-gray-50 dark:hover:bg-gray-750'
            }`}
          >
            <span className={`w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 ${
              isAll ? 'border-transparent' : 'border-gray-300 dark:border-gray-600'
            }`} style={isAll ? { backgroundColor: pl?.color, borderColor: pl?.color } : {}}>
              {isAll && <svg className="w-2.5 h-2.5 text-white" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>}
            </span>
            All Categories
          </button>

          {/* Category items */}
          {cats.map(cat => {
            const checked = !isAll && selected.includes(cat)
            return (
              <button
                key={cat}
                onClick={() => onToggleCategory(cat)}
                className={`w-full flex items-center gap-2.5 px-3.5 py-2 text-xs transition-colors ${
                  checked ? 'bg-gray-50 dark:bg-gray-750' : 'hover:bg-gray-50 dark:hover:bg-gray-750'
                }`}
              >
                <span className={`w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 ${
                  checked ? 'border-transparent' : 'border-gray-300 dark:border-gray-600'
                }`} style={checked ? { backgroundColor: pl?.color, borderColor: pl?.color } : {}}>
                  {checked && <svg className="w-2.5 h-2.5 text-white" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>}
                </span>
                <span className="text-gray-700 dark:text-gray-300">{cat}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
