import { computed, ref } from 'vue'

export function useBrowserNotifications() {
  const supported = typeof window !== 'undefined' && 'Notification' in window
  const permission = ref<NotificationPermission>(supported ? Notification.permission : 'denied')
  const granted = computed(() => permission.value === 'granted')

  async function request(): Promise<boolean> {
    if (!supported) return false
    if (Notification.permission === 'granted') {
      permission.value = 'granted'
      return true
    }
    const result = await Notification.requestPermission()
    permission.value = result
    return result === 'granted'
  }

  function notify(title: string, body: string, tag = 'ostium') {
    if (!supported || permission.value !== 'granted') return
    try {
      new Notification(title, { body, tag, icon: '/icons/icon-192.png', silent: false })
    } catch {
      /* some platforms only allow notifications from a service worker */
    }
  }

  return { supported, permission, granted, request, notify }
}
