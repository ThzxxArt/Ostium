import { useMessage } from 'naive-ui'
import { i18n } from '@/locales'

export function useCopy() {
  const message = useMessage()

  async function copy(value: string): Promise<boolean> {
    const copied = () => message.success(i18n.global.t('common.copied'))
    const failed = () => message.error(i18n.global.t('common.copy_failed'))
    try {
      await navigator.clipboard.writeText(value)
      copied()
      return true
    } catch {
      try {
        const area = document.createElement('textarea')
        area.value = value
        area.style.position = 'fixed'
        area.style.opacity = '0'
        document.body.appendChild(area)
        area.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(area)
        if (ok) copied()
        else failed()
        return ok
      } catch {
        failed()
        return false
      }
    }
  }

  return { copy }
}
