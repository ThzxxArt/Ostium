try {
  const stored = localStorage.getItem('ostium.theme') || 'system'
  const dark =
    stored === 'dark' ||
    (stored === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
} catch (_) {}
