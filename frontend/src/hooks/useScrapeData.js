import { useState, useCallback, useRef } from 'react'
import { API_BASE } from '../utils/constants'

export function useScrapeData() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [platformProgress, setPlatformProgress] = useState({})
  const abortRef = useRef(null)

  const scrape = useCallback(async (pincodes, platforms, categories = {}) => {
    setLoading(true)
    setError(null)
    setData(null)
    setPlatformProgress({})

    // Initialize progress for all platform/pincode combos
    const initial = {}
    for (const pc of pincodes) {
      for (const p of platforms) {
        initial[`${p}_${pc}`] = { status: 'pending', productCount: 0, message: 'Waiting...', platform: p, pincode: pc }
      }
    }
    setPlatformProgress(initial)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const res = await fetch(`${API_BASE}/scrape/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pincodes,
          platforms,
          categories,
          max_products_per_platform: 10000,
        }),
        signal: controller.signal,
      })

      if (!res.ok) throw new Error(`Server error: ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      const completedResults = []

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let eventType = null
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith('data: ') && eventType) {
            try {
              const payload = JSON.parse(line.slice(6))
              handleSSEEvent(eventType, payload, setPlatformProgress, completedResults, setData, pincodes)
            } catch {
              // ignore malformed JSON
            }
            eventType = null
          }
        }
      }

      return data
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Failed to fetch data')
      }
      return null
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }, [])

  return { data, loading, error, scrape, platformProgress }
}

function handleSSEEvent(event, payload, setPlatformProgress, completedResults, setData, pincodes) {
  const key = payload.platform && payload.pincode ? `${payload.platform}_${payload.pincode}` : null

  switch (event) {
    case 'started':
      setPlatformProgress(prev => {
        const next = { ...prev }
        for (const task of payload.tasks || []) {
          const k = `${task.platform}_${task.pincode}`
          next[k] = { ...next[k], status: 'scraping', message: 'Scraping...' }
        }
        return next
      })
      break

    case 'progress':
      if (key) {
        setPlatformProgress(prev => ({
          ...prev,
          [key]: { ...prev[key], status: 'scraping', productCount: payload.product_count, message: `${payload.product_count} products found` },
        }))
      }
      break

    case 'platform_complete':
      if (key) {
        const status = payload.status === 'failed' ? 'failed' : 'done'
        setPlatformProgress(prev => ({
          ...prev,
          [key]: {
            ...prev[key],
            status,
            productCount: payload.total_products,
            duration: payload.scrape_duration_seconds,
            message: status === 'failed' ? (payload.error_message || 'Failed') : `${payload.total_products} products in ${payload.scrape_duration_seconds}s`,
          },
        }))
        completedResults.push(payload)
      }
      break

    case 'done':
      setData({
        pincodes,
        results: completedResults.map(r => ({
          platform: r.platform,
          pincode: r.pincode,
          status: r.status,
          total_products: r.total_products,
          scrape_duration_seconds: r.scrape_duration_seconds,
          products: r.products || [],
          error_message: r.error_message,
        })),
        total_products: payload.total_products,
        total_duration_seconds: payload.total_duration_seconds,
      })
      break
  }
}

export function usePincodes() {
  const [pincodes, setPincodes] = useState(null)
  const [loading, setLoading] = useState(false)

  const fetchPincodes = useCallback(async () => {
    if (pincodes) return pincodes
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/pincodes`)
      const data = await res.json()
      setPincodes(data)
      return data
    } catch {
      return null
    } finally {
      setLoading(false)
    }
  }, [pincodes])

  return { pincodes, loading, fetchPincodes }
}
