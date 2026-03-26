import { PLATFORMS } from '../utils/constants'

export default function PlatformSelector({ selected, onChange }) {
  const toggle = (id) => onChange(selected.includes(id) ? selected.filter(p => p !== id) : [...selected, id])

  return (
    <div>
      <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Platforms</label>
      <div className="flex flex-wrap gap-3">
        {PLATFORMS.map(p => {
          const isActive = selected.includes(p.id)
          return (
            <button key={p.id} onClick={() => toggle(p.id)}
              className="relative flex items-center gap-2.5 px-5 py-3 rounded-xl border-2 text-sm font-semibold transition-all duration-200 hover:shadow-lg"
              style={{
                borderColor: isActive ? p.color : undefined,
                backgroundColor: isActive ? p.color + '15' : undefined,
                color: isActive ? p.color : undefined,
                boxShadow: isActive ? `0 0 20px ${p.color}15` : 'none',
              }}
              {...(!isActive && { className: "relative flex items-center gap-2.5 px-5 py-3 rounded-xl border-2 text-sm font-semibold transition-all duration-200 hover:shadow-lg border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-400 dark:text-gray-500" })}
            >
              <span className="w-5 h-5 rounded-md border-2 flex items-center justify-center transition-colors"
                style={isActive ? { borderColor: p.color, backgroundColor: p.color } : {}}
                {...(!isActive && { className: "w-5 h-5 rounded-md border-2 flex items-center justify-center transition-colors border-gray-300 dark:border-gray-600" })}>
                {isActive && <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>}
              </span>
              {p.name}
              {isActive && <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full animate-pulse" style={{ backgroundColor: p.color }}></span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}
