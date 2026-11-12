import { onMounted, onUnmounted, ref } from 'vue'

interface RegisterOptions {
  immediate?: boolean
  onRegisteredSW?: (swUrl: string, registration: ServiceWorkerRegistration | undefined) => void
  onRegisterError?: (error: unknown) => void
}

const UPDATE_INTERVAL_MS = 60 * 60 * 1000

export function useRegisterSW(options: RegisterOptions = {}) {
  const needRefresh = ref(false)
  const offlineReady = ref(false)
  let registration: ServiceWorkerRegistration | null = null
  let timer: ReturnType<typeof setInterval> | null = null

  const updateServiceWorker = async (reloadPage = true) => {
    const waiting = registration?.waiting
    if (waiting) {
      if (reloadPage) {
        navigator.serviceWorker.addEventListener(
          'controllerchange',
          () => window.location.reload(),
          {
            once: true,
          },
        )
      }
      waiting.postMessage({ type: 'SKIP_WAITING' })
      return
    }
    if (reloadPage) window.location.reload()
  }

  onMounted(async () => {
    if (!('serviceWorker' in navigator)) {
      offlineReady.value = true
      return
    }
    try {
      const reg = await navigator.serviceWorker.register('/sw.js')
      registration = reg
      options.onRegisteredSW?.('/sw.js', reg)
      if (reg.waiting) needRefresh.value = true
      reg.addEventListener('updatefound', () => {
        const installing = reg.installing
        if (!installing) return
        installing.addEventListener('statechange', () => {
          if (installing.state === 'installed' && navigator.serviceWorker.controller) {
            needRefresh.value = true
          }
        })
      })
      timer = setInterval(() => {
        void reg.update()
      }, UPDATE_INTERVAL_MS)
    } catch (error) {
      options.onRegisterError?.(error)
    }
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { needRefresh, offlineReady, updateServiceWorker }
}
