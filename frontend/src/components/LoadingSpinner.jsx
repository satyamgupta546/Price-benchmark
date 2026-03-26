import { PLATFORMS } from '../utils/constants'

const STATUS_CONFIG = {
  pending:  { icon: '\u23F3', label: 'Pending',  color: 'text-gray-400 dark:text-gray-500', bg: 'bg-gray-50 dark:bg-gray-800/50', border: 'border-gray-200 dark:border-gray-700' },
  scraping: { icon: null,     label: 'Scraping', color: 'text-blue-600 dark:text-purple-400', bg: 'bg-blue-50/50 dark:bg-purple-900/20', border: 'border-blue-200 dark:border-purple-700' },
  done:     { icon: '\u2705', label: 'Done',     color: 'text-green-600 dark:text-green-400', bg: 'bg-green-50/50 dark:bg-green-900/20', border: 'border-green-200 dark:border-green-700' },
  failed:   { icon: '\u274C', label: 'Failed',   color: 'text-red-500 dark:text-red-400', bg: 'bg-red-50/50 dark:bg-red-900/20', border: 'border-red-200 dark:border-red-700' },
}

export default function LoadingSpinner({ platforms = [], platformProgress = {} }) {
  const entries = Object.entries(platformProgress)
  const hasProgress = entries.length > 0

  const totalTasks = entries.length || platforms.length
  const doneTasks = entries.filter(([, v]) => v.status === 'done' || v.status === 'failed').length
  const progressPct = totalTasks > 0 ? Math.round((doneTasks / totalTasks) * 100) : 0

  return (
    <div className="flex flex-col items-center py-10 px-4">
      {/* Overall progress */}
      <div className="w-full max-w-md mb-6">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 border-[2.5px] border-blue-600 dark:border-purple-500 rounded-full border-t-transparent animate-spin"></div>
            <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">Scraping product data...</span>
          </div>
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">{doneTasks}/{totalTasks} platforms</span>
        </div>
        <div className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-purple-500 dark:to-indigo-500 rounded-full transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Per-platform cards */}
      {hasProgress ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 w-full max-w-2xl">
          {entries.map(([key, info]) => {
            const pl = PLATFORMS.find(p => p.id === info.platform)
            const cfg = STATUS_CONFIG[info.status] || STATUS_CONFIG.pending
            return (
              <div key={key} className={`flex items-start gap-3 rounded-xl border p-3 ${cfg.bg} ${cfg.border} transition-all`}>
                <div className="flex-shrink-0 mt-0.5">
                  {info.status === 'scraping' ? (
                    <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: (pl?.color || '#666') + '40', borderTopColor: pl?.color || '#666' }}></div>
                  ) : (
                    <span className="text-base leading-none">{cfg.icon}</span>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: pl?.color }}></span>
                    <span className="text-sm font-semibold text-gray-800 dark:text-gray-200 truncate">{pl?.name || info.platform}</span>
                  </div>
                  <p className={`text-xs mt-0.5 ${cfg.color} truncate`}>{info.message}</p>
                  {info.productCount > 0 && (
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{info.productCount} products{info.duration ? ` \u00B7 ${info.duration}s` : ''}</p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        /* Fallback if no progress data yet */
        <div className="flex flex-wrap gap-2 justify-center">
          {platforms.map(pid => {
            const p = PLATFORMS.find(pl => pl.id === pid)
            return p ? (
              <span key={p.id} className="px-3 py-1 rounded-full text-xs font-medium border" style={{ borderColor: p.color + '40', color: p.color, backgroundColor: p.color + '15' }}>
                {p.name}
              </span>
            ) : null
          })}
        </div>
      )}
    </div>
  )
}
