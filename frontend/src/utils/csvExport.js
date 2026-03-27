import { API_BASE } from './constants'

export async function downloadExcel(pincodes, platforms) {
  try {
    const params = new URLSearchParams({ pincode: pincodes })
    if (platforms) params.append('platforms', platforms)

    const res = await fetch(`${API_BASE}/export/excel?${params}`)
    if (!res.ok) {
      console.error('Export failed:', res.status)
      return
    }

    const blob = await res.blob()
    const url = URL.createObjectURL(blob)

    // Extract filename from Content-Disposition header or generate one
    const disposition = res.headers.get('Content-Disposition')
    const filenameMatch = disposition?.match(/filename=(.+)/)
    const filename = filenameMatch ? filenameMatch[1] : `PriceBenchmark_${new Date().toISOString().split('T')[0]}.xlsx`

    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch (err) {
    console.error('Excel download error:', err)
  }
}
