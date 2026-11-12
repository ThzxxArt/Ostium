<script setup lang="ts">
import { computed } from 'vue'
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
import OJobDrawer from '@/components/OJobDrawer.vue'
import OPwaUpdate from '@/components/OPwaUpdate.vue'
import OShortcutModal from '@/components/OShortcutModal.vue'
import { useAppStore } from '@/stores/app'
import { useI18n } from 'vue-i18n'
import { darkThemeOverrides, lightThemeOverrides } from '@/design/theme'

const app = useAppStore()
const { locale } = useI18n()

const theme = computed(() => (app.isDark ? darkTheme : null))
const overrides = computed(() => (app.isDark ? darkThemeOverrides : lightThemeOverrides))
const naiveLocale = computed(() => (locale.value.startsWith('zh') ? zhCN : enUS))
const naiveDateLocale = computed(() => (locale.value.startsWith('zh') ? dateZhCN : dateEnUS))
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
            <RouterView />
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
