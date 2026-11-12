import { createI18n } from 'vue-i18n'
import en from './en'
import zh from './zh'

const stored = (() => {
  try {
    return localStorage.getItem('ostium.locale')
  } catch {
    return null
  }
})()

export const i18n = createI18n({
  legacy: false,
  locale: stored || (navigator.language.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US'),
  fallbackLocale: 'en-US',
  messages: {
    'zh-CN': zh,
    'en-US': en,
  },
})

export function setLocale(locale: string) {
  i18n.global.locale.value = locale as 'zh-CN' | 'en-US'
  try {
    localStorage.setItem('ostium.locale', locale)
  } catch {
    /* ignore */
  }
}

export function currentLocale(): string {
  return i18n.global.locale.value
}
