const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
})

export function formatPrice(price: number): string {
  return usd.format(price)
}

export function truncate(text: string, max = 90): string {
  if (text.length <= max) return text
  return `${text.slice(0, max).trimEnd()}…`
}

// Turns a product slug like "basic-hoodie-big-yale" into "basic hoodie big yale".
export function slugToWords(slug: string): string {
  return slug.replace(/-/g, ' ')
}
