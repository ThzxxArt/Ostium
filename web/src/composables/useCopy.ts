import { useMessage } from 'naive-ui'

export function useCopy() {
  const message = useMessage()

  async function copy(value: string): Promise<boolean> {
    try {
      await navigator.clipboard.writeText(value)
      message.success('Copied')
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
        if (ok) message.success('Copied')
        else message.error('Copy failed; select the text manually')
        return ok
      } catch {
        message.error('Copy failed; select the text manually')
        return false
      }
    }
  }

  return { copy }
}
