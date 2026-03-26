export default function ErrorBanner({ message, onDismiss, type = 'error' }) {
  if (!message) return null
  const s = type === 'warning'
    ? { wrap: 'bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-700/50', icon: 'text-amber-500 dark:text-amber-400', text: 'text-amber-800 dark:text-amber-300' }
    : { wrap: 'bg-red-50 dark:bg-red-900/30 border-red-200 dark:border-red-700/50', icon: 'text-red-500 dark:text-red-400', text: 'text-red-800 dark:text-red-300' }
  return (
    <div className={`${s.wrap} border rounded-xl p-4 flex items-start gap-3`}>
      <svg className={`w-5 h-5 ${s.icon} mt-0.5 flex-shrink-0`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <p className={`text-sm ${s.text} flex-1`}>{message}</p>
      {onDismiss && <button onClick={onDismiss} className={`${s.icon} hover:opacity-70`}><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg></button>}
    </div>
  )
}
