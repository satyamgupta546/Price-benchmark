import { useState, useCallback, useRef } from 'react'
import { API_BASE } from '../utils/constants'

export function useCompare() {
  const [uploadInfo, setUploadInfo] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [progress, setProgress] = useState(null)
  // progress shape: { total, platforms: [...], byPlatform: { blinkit: { current, matched, not_found, product }, ... } }
  const [error, setError] = useState(null)
  const [done, setDone] = useState(false)
  const [doneData, setDoneData] = useState(null)
  const abortRef = useRef(null)

  const upload = useCallback(async (file) => {
    setUploading(true)
    setError(null)
    setUploadInfo(null)
    setProgress(null)
    setDone(false)
    setDoneData(null)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const res = await fetch(`${API_BASE}/compare/upload`, {
        method: 'POST',
        body: formData,
      })

      const data = await res.json()
      if (data.error) {
        setError(data.error)
        return null
      }
      setUploadInfo(data)
      return data
    } catch (err) {
      setError(err.message || 'Upload failed')
      return null
    } finally {
      setUploading(false)
    }
  }, [])

  const startCompare = useCallback(async (pincode, platforms) => {
    setComparing(true)
    setError(null)
    setProgress(null)
    setDone(false)
    setDoneData(null)

    const controller = new AbortController()
    abortRef.current = controller

    const platformParam = platforms.join(',')

    try {
      const res = await fetch(`${API_BASE}/compare/stream?pincode=${pincode}&platforms=${platformParam}`, {
        method: 'POST',
        signal: controller.signal,
      })

      if (!res.ok) throw new Error(`Server error: ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done: streamDone, value } = await reader.read()
        if (streamDone) break

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

              if (eventType === 'started') {
                const byPlatform = {}
                for (const p of payload.platforms) {
                  byPlatform[p] = { current: 0, total: payload.total, matched: 0, not_found: 0, product: '' }
                }
                setProgress({ total: payload.total, platforms: payload.platforms, byPlatform })
              } else if (eventType === 'progress') {
                setProgress(prev => {
                  if (!prev) return prev
                  return {
                    ...prev,
                    byPlatform: {
                      ...prev.byPlatform,
                      [payload.platform]: {
                        current: payload.current,
                        total: prev.total,
                        matched: payload.matched,
                        not_found: payload.not_found,
                        product: payload.product,
                        status: payload.status,
                      }
                    }
                  }
                })
              } else if (eventType === 'platform_error') {
                setProgress(prev => {
                  if (!prev) return prev
                  return {
                    ...prev,
                    byPlatform: {
                      ...prev.byPlatform,
                      [payload.platform]: {
                        ...(prev.byPlatform[payload.platform] || {}),
                        error: payload.error,
                      }
                    }
                  }
                })
              } else if (eventType === 'done') {
                setDoneData(payload)
                setDone(true)
              } else if (eventType === 'error') {
                setError(payload.message)
              }
            } catch {
              // ignore malformed JSON
            }
            eventType = null
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Comparison failed')
      }
    } finally {
      setComparing(false)
      abortRef.current = null
    }
  }, [])

  const downloadResult = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/compare/download`)
      if (!res.ok) {
        const data = await res.json()
        setError(data.error || 'Download failed')
        return
      }

      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const disposition = res.headers.get('Content-Disposition')
      const match = disposition?.match(/filename=(.+)/)
      const filename = match ? match[1] : 'comparison.xlsx'

      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err.message || 'Download failed')
    }
  }, [])

  const reset = useCallback(() => {
    setUploadInfo(null)
    setProgress(null)
    setError(null)
    setDone(false)
    setDoneData(null)
    setComparing(false)
    setUploading(false)
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
  }, [])

  return { uploadInfo, uploading, comparing, progress, error, done, doneData, upload, startCompare, downloadResult, reset }
}
