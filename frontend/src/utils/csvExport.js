import { PLATFORMS } from './constants'

export function downloadCSV(products, pincode) {
  const date = new Date().toISOString().split('T')[0]
  const filename = `PriceBenchmark_${pincode}_${date}.csv`

  // Find which platforms have data
  const activePlatforms = PLATFORMS.filter(p =>
    products.some(pr => pr.platform === p.id)
  )

  // Group products by normalized name for comparison
  const map = {}
  for (const p of products) {
    const key = p.product_name?.toLowerCase().replace(/\s+/g, ' ').trim()
    if (!key) continue
    if (!map[key]) {
      map[key] = {
        product_name: p.product_name,
        brand: p.brand || '',
        unit: p.unit || '',
        category: p.category || '',
        pincode: p.pincode || '',
        prices: {},
      }
    }
    // Store price info per platform
    if (!map[key].prices[p.platform] || p.price > 0) {
      map[key].prices[p.platform] = {
        price: p.price || 0,
        mrp: p.mrp || 0,
        in_stock: p.in_stock,
      }
    }
  }

  const rows = Object.values(map).sort((a, b) =>
    a.product_name.localeCompare(b.product_name)
  )

  // Build headers
  const headers = ['sr_no', 'product_name', 'brand', 'unit', 'category', 'pincode']
  for (const p of activePlatforms) {
    headers.push(`${p.name}_price`, `${p.name}_mrp`, `${p.name}_stock`)
  }
  headers.push('cheapest_platform', 'cheapest_price', 'price_diff')

  // Build CSV rows
  const csvRows = rows.map((item, i) => {
    const cols = [
      i + 1,
      `"${item.product_name.replace(/"/g, '""')}"`,
      `"${item.brand.replace(/"/g, '""')}"`,
      `"${item.unit}"`,
      `"${item.category}"`,
      item.pincode,
    ]

    const validPrices = []
    for (const p of activePlatforms) {
      const info = item.prices[p.id]
      if (info) {
        cols.push(
          info.price > 0 ? info.price.toFixed(2) : '',
          info.mrp > 0 ? info.mrp.toFixed(2) : '',
          info.in_stock ? 'Yes' : 'No'
        )
        if (info.price > 0) validPrices.push({ name: p.name, price: info.price })
      } else {
        cols.push('', '', '')
      }
    }

    // Cheapest platform
    if (validPrices.length > 0) {
      validPrices.sort((a, b) => a.price - b.price)
      const cheapest = validPrices[0]
      const most = validPrices[validPrices.length - 1]
      cols.push(
        cheapest.name,
        cheapest.price.toFixed(2),
        validPrices.length > 1 ? (most.price - cheapest.price).toFixed(2) : '0.00'
      )
    } else {
      cols.push('', '', '')
    }

    return cols.join(',')
  })

  const csv = [headers.join(','), ...csvRows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)

  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
