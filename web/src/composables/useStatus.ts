import { onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api'
import type { ConnectionMode } from '@/api/types'

export function useStatus() {
  const auth = useAuthStore()
  const coreRunning = ref(false)
  const coreReachable = ref(false)
  const mode = ref<ConnectionMode>('mixed')
  const version = ref('0.1.1')
  const serverHost = ref<string | null>(null)
  const loading = ref(false)
  let timer: number | null = null

  async function refresh() {
    if (document.hidden) return
    if (!auth.authenticated) return
    loading.value = true
    try {
      const info = await api.system.info()
      version.value = info.app.version
      mode.value = info.mode
      serverHost.value = info.server_host
      coreRunning.value = Boolean((info.core as Record<string, unknown>).running)
      coreReachable.value = true
    } catch {
      coreReachable.value = false
    } finally {
      loading.value = false
    }
  }

  function start() {
    void refresh()
    if (timer === null) timer = window.setInterval(refresh, 10_000)
  }

  function stop() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  watch(
    () => auth.authenticated,
    (value) => (value ? start() : stop()),
    { immediate: true },
  )

  onBeforeUnmount(stop)

  return { coreRunning, coreReachable, mode, version, serverHost, loading, refresh }
}
