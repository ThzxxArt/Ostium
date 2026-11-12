/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

declare module 'virtual:pwa-register/vue' {
  import type { Ref } from 'vue'
  export function useRegisterSW(options?: {
    immediate?: boolean
    onRegisteredSW?: (swUrl: string, registration: ServiceWorkerRegistration | undefined) => void
    onRegisterError?: (error: unknown) => void
  }): {
    needRefresh: Ref<boolean>
    offlineReady: Ref<boolean>
    updateServiceWorker: (reloadPage?: boolean) => Promise<void>
  }
}
