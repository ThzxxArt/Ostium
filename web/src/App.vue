<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NConfigProvider,
  NDialogProvider,
  NLoadingBarProvider,
  NMessageProvider,
  NNotificationProvider,
  darkTheme,
  dateEnUS,
  dateZhCN,
  enUS,
  zhCN,
} from 'naive-ui'
import OCommandPalette from '@/components/OCommandPalette.vue'
import OErrorBoundary from '@/components/OErrorBoundary.vue'
import OJobDrawer from '@/components/OJobDrawer.vue'
import OPwaUpdate from '@/components/OPwaUpdate.vue'
import OShortcutModal from '@/components/OShortcutModal.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from 'vue-i18n'
import { darkThemeOverrides, lightThemeOverrides } from '@/design/theme'

const app = useAppStore()
const auth = useAuthStore()
const { locale } = useI18n()
const router = useRouter()
const route = useRoute()

const theme = computed(() => (app.isDark ? darkTheme : null))
const overrides = computed(() => (app.isDark ? darkThemeOverrides : lightThemeOverrides))
const naiveLocale = computed(() => (locale.value.startsWith('zh') ? zhCN : enUS))
const naiveDateLocale = computed(() => (locale.value.startsWith('zh') ? dateZhCN : dateEnUS))

function onUnauthorized() {
  auth.expire()
  if (route.path === '/login') return
  void router.replace({ path: '/login', query: { next: route.fullPath } })
}

onMounted(() => window.addEventListener('ostium:unauthorized', onUnauthorized))
onBeforeUnmount(() => window.removeEventListener('ostium:unauthorized', onUnauthorized))
</script>

<template>
  <NConfigProvider
    :theme="theme"
    :theme-overrides="overrides"
    :locale="naiveLocale"
    :date-locale="naiveDateLocale"
    abstract
  >
    <NLoadingBarProvider>
      <NDialogProvider>
        <NNotificationProvider>
          <NMessageProvider>
            <OErrorBoundary>
              <RouterView />
            </OErrorBoundary>
            <OCommandPalette />
            <OJobDrawer v-model:show="app.jobDrawerOpen" />
            <OShortcutModal />
            <OPwaUpdate />
          </NMessageProvider>
        </NNotificationProvider>
      </NDialogProvider>
    </NLoadingBarProvider>
  </NConfigProvider>
</template>
