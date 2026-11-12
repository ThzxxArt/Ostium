import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { ThemeMode } from '@/api/types'
import { setLocale, currentLocale } from '@/locales'

function storedTheme(): ThemeMode {
  try {
    const value = localStorage.getItem('ostium.theme')
    if (value === 'light' || value === 'dark' || value === 'system') return value
  } catch {
    /* ignore */
  }
  return 'dark'
}

export const useAppStore = defineStore('app', () => {
  const theme = ref<ThemeMode>(storedTheme())
  const sidebarCollapsed = ref(false)
  const mobileNavOpen = ref(false)
  const commandOpen = ref(false)
  const shortcutsOpen = ref(false)
  const jobDrawerOpen = ref(false)
  const locale = ref(currentLocale())
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const systemDark = ref(media.matches)

  media.addEventListener('change', (event) => {
    systemDark.value = event.matches
    if (theme.value === 'system') applyTheme()
  })

  const isDark = computed(() =>
    theme.value === 'system' ? systemDark.value : theme.value === 'dark',
  )

  function applyTheme() {
    document.documentElement.dataset.theme = isDark.value ? 'dark' : 'light'
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', isDark.value ? '#060911' : '#F4F7FC')
  }

  function setTheme(value: ThemeMode) {
    theme.value = value
    try {
      localStorage.setItem('ostium.theme', value)
    } catch {
      /* ignore */
    }
    applyTheme()
  }

  function toggleTheme() {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  function toggleLanguage() {
    const next = locale.value.startsWith('zh') ? 'en-US' : 'zh-CN'
    locale.value = next
    setLocale(next)
  }

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
    try {
      localStorage.setItem('ostium.sidebar', sidebarCollapsed.value ? 'collapsed' : 'open')
    } catch {
      /* ignore */
    }
  }

  function restoreSidebar() {
    try {
      sidebarCollapsed.value = localStorage.getItem('ostium.sidebar') === 'collapsed'
    } catch {
      /* ignore */
    }
  }

  applyTheme()

  return {
    theme,
    isDark,
    sidebarCollapsed,
    mobileNavOpen,
    commandOpen,
    shortcutsOpen,
    jobDrawerOpen,
    locale,
    setTheme,
    toggleTheme,
    toggleLanguage,
    toggleSidebar,
    restoreSidebar,
  }
})
