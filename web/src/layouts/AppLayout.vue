<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NBadge,
  NDrawer,
  NDrawerContent,
  NDropdown,
  NPopover,
  NTooltip,
  useMessage,
} from 'naive-ui'
import {
  Bell,
  ChevronDown,
  Command,
  Languages,
  ListChecks,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Sun,
} from '@lucide/vue'
import OBrandMark from '@/components/OBrandMark.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import { clientNav, clientQuickNav, serverNav } from '@/router/nav'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useEventStore } from '@/stores/events'
import { useStatus } from '@/composables/useStatus'
import { useBrowserNotifications } from '@/composables/useBrowserNotifications'
import { api } from '@/api'
import type { Alert } from '@/api/types'
import { relativeTime } from '@/utils/format'

const app = useAppStore()
const auth = useAuthStore()
const events = useEventStore()
const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t, locale } = useI18n()
const { coreRunning, coreReachable, version } = useStatus()
const browserNotifications = useBrowserNotifications()

const alerts = ref<Alert[]>([])
const alertsOpen = ref(false)
const userOpen = ref(false)
const statusOpen = ref(false)

const groups = computed(() => (auth.isServer ? serverNav : clientNav))
const flatNav = computed(() => groups.value.flatMap((group) => group.items))
const currentItem = computed(() => flatNav.value.find((item) => item.path === route.path))
const pageTitle = computed(() => {
  if (route.name === 'home') return auth.isServer ? t('nav.dashboard') : t('nav.home')
  if (route.meta.titleKey) return t(String(route.meta.titleKey))
  return currentItem.value ? t(currentItem.value.labelKey) : t('app.name')
})

const connectionState = computed(() => {
  if (!coreReachable.value) return 'degraded'
  return coreRunning.value ? 'connected' : 'disconnected'
})
const connectionLabel = computed(() => {
  if (!coreReachable.value) return t('status.degraded')
  return coreRunning.value ? t('status.connected') : t('status.disconnected')
})

const notificationCount = computed(
  () => alerts.value.filter((alert) => !alert.acknowledged_at).length,
)

const userOptions = computed(() => [
  { key: 'settings', label: t('nav.settings') },
  { key: 'shortcuts', label: t('command.shortcuts') },
  { type: 'divider', key: 'divider' },
  { key: 'logout', label: t('auth.logout') },
])

const statusOptions = computed(() => {
  if (auth.isClient) {
    return [
      { key: 'home', label: t('nav.home') },
      { key: 'network', label: t('nav.network') },
      { key: 'diagnostics', label: t('nav.diagnostics') },
    ]
  }
  return [
    { key: 'system', label: t('nav.system') },
    { key: 'logs', label: t('nav.logs') },
    { key: 'jobs', label: t('nav.jobs') },
  ]
})

async function loadAlerts() {
  try {
    alerts.value = (await api.alerts.list()).alerts
  } catch {
    alerts.value = []
  }
}

async function ackAlert(alert: Alert) {
  try {
    await api.alerts.ack(alert.id)
    alert.acknowledged_at = new Date().toISOString()
  } catch {
    /* ignore */
  }
}

function onUserSelect(key: string) {
  userOpen.value = false
  if (key === 'logout') {
    void auth.logout().then(() => router.push('/login'))
  } else if (key === 'settings') {
    void router.push('/settings')
  } else if (key === 'shortcuts') {
    app.shortcutsOpen = true
  }
}

function onStatusSelect(key: string) {
  statusOpen.value = false
  void router.push(key === 'home' ? '/' : `/${key}`)
}

function toggleNavDrawer() {
  app.mobileNavOpen = !app.mobileNavOpen
}

let goPrefix = false
let goTimer: number | null = null

function isTyping(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  return (
    !!element &&
    (element.tagName === 'INPUT' ||
      element.tagName === 'TEXTAREA' ||
      element.tagName === 'SELECT' ||
      element.isContentEditable)
  )
}

async function toggleConnection() {
  if (!auth.isClient) return
  try {
    if (coreRunning.value) {
      await api.system.disconnect()
      message.success(t('home.disconnected'))
    } else {
      await api.system.connect()
      message.success(t('home.connected'))
    }
    window.setTimeout(() => window.location.reload(), 400)
  } catch (err) {
    message.error((err as Error).message)
  }
}

function onKeydown(event: KeyboardEvent) {
  if (isTyping(event.target)) return
  const meta = event.metaKey || event.ctrlKey
  if (meta && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    app.commandOpen = !app.commandOpen
    return
  }
  if (event.key === '/') {
    event.preventDefault()
    const search = document.querySelector<HTMLInputElement>(
      'input[type="search"], input[data-search]',
    )
    search?.focus()
    return
  }
  if (event.key === '?') {
    event.preventDefault()
    app.shortcutsOpen = true
    return
  }
  if (event.key === 'Escape') {
    app.commandOpen = false
    app.shortcutsOpen = false
    return
  }
  if (event.key.toLowerCase() === 'g') {
    goPrefix = true
    if (goTimer !== null) clearTimeout(goTimer)
    goTimer = window.setTimeout(() => (goPrefix = false), 1200)
    return
  }
  if (goPrefix) {
    const map: Record<string, string> = auth.isServer
      ? { d: '/', u: '/users', c: '/connections', r: '/rules', l: '/logs', s: '/settings' }
      : { d: '/', u: '/profiles', c: '/network', r: '/routing', l: '/logs', s: '/settings' }
    const path = map[event.key.toLowerCase()]
    if (path) {
      event.preventDefault()
      goPrefix = false
      void router.push(path)
    }
    return
  }
  if (event.key.toLowerCase() === 'c' && auth.isClient) {
    event.preventDefault()
    void toggleConnection()
  }
}

function openJobs() {
  app.jobDrawerOpen = true
}

watch(
  () => events.lastAlert,
  (frame) => {
    if (frame?.data?.message) {
      browserNotifications.notify(t('dashboard.alerts'), String(frame.data.message), 'ostium-alert')
    }
    void loadAlerts()
  },
)

watch(
  () => events.lastJob,
  (frame) => {
    const status = String(frame?.data?.status || '')
    if (status === 'succeeded' || status === 'failed') {
      browserNotifications.notify(
        status === 'succeeded' ? t('notify.job_done') : t('notify.job_failed'),
        String(frame?.data?.type || ''),
        `ostium-job-${String(frame?.data?.id || '')}`,
      )
    }
    if (app.jobDrawerOpen) void loadAlerts()
  },
)

onMounted(() => {
  app.restoreSidebar()
  window.addEventListener('keydown', onKeydown)
  events.connect()
  void loadAlerts()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  events.disconnect()
  if (goTimer !== null) clearTimeout(goTimer)
})
</script>

<template>
  <div class="shell" :class="{ collapsed: app.sidebarCollapsed }">
    <a class="skip-link" href="#main-content">{{ t('common.skip') || 'Skip to content' }}</a>

    <aside class="sidebar o-glass" aria-label="Primary navigation">
      <div class="sidebar-head">
        <RouterLink to="/" class="brand-link" :aria-label="t('app.name')">
          <OBrandMark :size="34" :wordmark="!app.sidebarCollapsed" />
        </RouterLink>
        <button
          type="button"
          class="icon-btn collapse-btn"
          :aria-label="app.sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          @click="app.toggleSidebar()"
        >
          <component :is="app.sidebarCollapsed ? PanelLeftOpen : PanelLeftClose" :size="17" />
        </button>
      </div>

      <nav class="nav o-scroll">
        <div v-for="group in groups" :key="group.key" class="nav-group">
          <p v-if="!app.sidebarCollapsed" class="group-label">{{ t(group.labelKey) }}</p>
          <RouterLink
            v-for="item in group.items"
            :key="item.key"
            :to="item.path"
            class="nav-item"
            :class="{ active: route.path === item.path }"
            :title="app.sidebarCollapsed ? t(item.labelKey) : undefined"
          >
            <component :is="item.icon" :size="18" :stroke-width="1.7" class="nav-icon" />
            <span v-if="!app.sidebarCollapsed" class="nav-label">{{ t(item.labelKey) }}</span>
          </RouterLink>
        </div>
      </nav>

      <div class="sidebar-foot">
        <div v-if="!app.sidebarCollapsed" class="foot-card">
          <div class="foot-row">
            <span class="dot" :class="coreRunning ? 'ok' : 'off'" />
            <span>{{
              coreRunning ? t('dashboard.engine_running') : t('dashboard.engine_stopped')
            }}</span>
          </div>
          <p class="o-micro o-subtle">{{ t('footer.version', { version }) }}</p>
        </div>
      </div>
    </aside>

    <div class="main-column">
      <header class="topbar o-glass">
        <button
          type="button"
          class="icon-btn mobile-menu"
          aria-label="Open navigation"
          @click="toggleNavDrawer"
        >
          <Menu :size="19" />
        </button>
        <div class="breadcrumb">
          <span class="crumb-root">{{ auth.isServer ? t('app.name') : t('nav.home') }}</span>
          <span class="cr divider">/</span>
          <span class="current">{{ pageTitle }}</span>
        </div>

        <div class="topbar-spacer" />

        <NDropdown :options="statusOptions" trigger="click" @select="onStatusSelect">
          <button type="button" class="status-button" :aria-label="connectionLabel">
            <OStatusPill :status="connectionState" :label="connectionLabel" :pulse="coreRunning" />
          </button>
        </NDropdown>

        <button type="button" class="search-button" @click="app.commandOpen = true">
          <Search :size="15" :stroke-width="1.8" />
          <span class="search-label">{{ t('common.search') }}</span>
          <kbd><Command :size="10" />K</kbd>
        </button>

        <NTooltip>
          <template #trigger>
            <button type="button" class="icon-btn" :aria-label="t('nav.jobs')" @click="openJobs">
              <ListChecks :size="18" :stroke-width="1.7" />
            </button>
          </template>
          {{ t('nav.jobs') }}
        </NTooltip>

        <NPopover
          v-model:show="alertsOpen"
          trigger="click"
          placement="bottom-end"
          :width="360"
          @update:show="loadAlerts"
        >
          <template #trigger>
            <button type="button" class="icon-btn" :aria-label="t('dashboard.alerts')">
              <NBadge :value="notificationCount" :max="9" :show="notificationCount > 0" dot>
                <Bell :size="18" :stroke-width="1.7" />
              </NBadge>
            </button>
          </template>
          <div class="alerts">
            <div class="alerts-head">
              <strong>{{ t('dashboard.alerts') }}</strong>
              <span class="o-micro o-subtle">{{ notificationCount }}</span>
            </div>
            <div v-if="!alerts.length" class="alerts-empty">{{ t('dashboard.no_alerts') }}</div>
            <ul v-else class="alert-list">
              <li v-for="alert in alerts" :key="alert.id" class="alert">
                <span class="alert-dot" :class="alert.level" />
                <div class="alert-copy">
                  <p>{{ alert.message }}</p>
                  <span class="o-micro o-subtle">{{ relativeTime(alert.created_at, locale) }}</span>
                </div>
                <button type="button" class="alert-ack" @click="ackAlert(alert)">✓</button>
              </li>
            </ul>
          </div>
        </NPopover>

        <NTooltip>
          <template #trigger>
            <button
              type="button"
              class="icon-btn"
              :aria-label="t('common.actions')"
              @click="app.toggleTheme()"
            >
              <component :is="app.isDark ? Sun : Moon" :size="18" :stroke-width="1.7" />
            </button>
          </template>
          {{ app.isDark ? t('settings.theme_light') : t('settings.theme_dark') }}
        </NTooltip>

        <NTooltip>
          <template #trigger>
            <button type="button" class="icon-btn lang-btn" @click="app.toggleLanguage()">
              <Languages :size="17" :stroke-width="1.7" />
              <span class="lang-code">{{ locale.startsWith('zh') ? '中' : 'EN' }}</span>
            </button>
          </template>
          {{ t('settings.language') }}
        </NTooltip>

        <NDropdown
          v-model:show="userOpen"
          :options="userOptions"
          trigger="click"
          @select="onUserSelect"
        >
          <button type="button" class="user-button">
            <span class="avatar">{{ (auth.me?.username || 'A').slice(0, 1).toUpperCase() }}</span>
            <span class="user-name">{{ auth.me?.username }}</span>
            <ChevronDown :size="13" />
          </button>
        </NDropdown>
      </header>

      <main id="main-content" class="content" tabindex="-1">
        <RouterView v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>

      <footer class="app-footer">
        <span>{{ t('footer.privacy') }}</span>
        <span class="dot-sep">·</span>
        <a href="https://github.com/ThzxxArt/Ostium" target="_blank" rel="noopener">{{
          t('footer.github')
        }}</a>
        <span class="dot-sep">·</span>
        <span>{{ t('footer.version', { version }) }}</span>
      </footer>
    </div>

    <nav class="mobile-nav o-glass" aria-label="Mobile navigation">
      <RouterLink
        v-for="item in auth.isServer
          ? [
              serverNav[0].items[0],
              serverNav[0].items[2],
              serverNav[1].items[0],
              serverNav[3].items[0],
            ]
          : clientQuickNav"
        :key="item.key"
        :to="item.path"
        class="mobile-item"
        :class="{ active: route.path === item.path }"
      >
        <component :is="item.icon" :size="19" :stroke-width="1.7" />
        <span>{{ t(item.labelKey) }}</span>
      </RouterLink>
      <button type="button" class="mobile-item" @click="toggleNavDrawer">
        <Menu :size="19" :stroke-width="1.7" />
        <span>{{ t('common.actions') }}</span>
      </button>
    </nav>

    <NDrawer v-model:show="app.mobileNavOpen" placement="left" :width="300">
      <NDrawerContent closable>
        <template #header><OBrandMark :size="30" /></template>
        <nav class="drawer-nav">
          <div v-for="group in groups" :key="group.key" class="drawer-group">
            <p class="group-label">{{ t(group.labelKey) }}</p>
            <RouterLink
              v-for="item in group.items"
              :key="item.key"
              :to="item.path"
              class="nav-item"
              :class="{ active: route.path === item.path }"
              @click="app.mobileNavOpen = false"
            >
              <component :is="item.icon" :size="18" :stroke-width="1.7" />
              <span>{{ t(item.labelKey) }}</span>
            </RouterLink>
          </div>
        </nav>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
}
.sidebar {
  position: fixed;
  z-index: 40;
  inset: 0 auto 0 0;
  width: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--surface) 90%, transparent);
  border-right: 1px solid var(--border);
  transition: width var(--dur) var(--ease);
}
.collapsed .sidebar {
  width: var(--sidebar-collapsed);
}
.sidebar-head {
  height: var(--topbar-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px 0 20px;
  gap: 8px;
}
.brand-link {
  display: inline-flex;
  min-width: 0;
}
.collapse-btn {
  opacity: 0.6;
}
.collapse-btn:hover {
  opacity: 1;
}
.nav {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px 18px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.nav-group {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.group-label {
  padding: 0 12px 6px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-3);
}
.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 11px;
  min-height: 42px;
  padding: 0 12px;
  border-radius: 10px;
  color: var(--text-2);
  font-size: 13px;
  font-weight: 500;
  transition:
    background var(--dur) var(--ease),
    color var(--dur) var(--ease);
}
.nav-item:hover {
  background: var(--surface-2);
  color: var(--text);
}
.nav-item.active {
  background: var(--accent-soft);
  color: var(--accent);
}
.nav-item.active::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 9px;
  bottom: 9px;
  width: 3px;
  border-radius: 0 4px 4px 0;
  background: var(--accent);
}
.nav-icon {
  flex: none;
}
.nav-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sidebar-foot {
  padding: 12px;
  border-top: 1px solid var(--border);
}
.foot-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--surface-2);
}
.foot-row {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: var(--text-2);
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}
.dot.ok {
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
}
.dot.off {
  background: var(--text-3);
}
.main-column {
  flex: 1;
  min-width: 0;
  margin-left: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  transition: margin-left var(--dur) var(--ease);
}
.collapsed .main-column {
  margin-left: var(--sidebar-collapsed);
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  height: var(--topbar-height);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 24px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg) 78%, transparent);
}
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-3);
  min-width: 0;
}
.crumb-root {
  white-space: nowrap;
}
.current {
  color: var(--text);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar-spacer {
  flex: 1;
}
.status-button {
  border: 0;
  background: transparent;
  padding: 0;
  cursor: pointer;
}
.search-button {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 9px 0 11px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-3);
  cursor: pointer;
  font-size: 12px;
}
.search-button:hover {
  border-color: var(--border-strong);
  color: var(--text-2);
}
.search-label {
  min-width: 44px;
  text-align: left;
}
.search-button kbd {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  height: 20px;
  padding: 0 5px;
  border-radius: 5px;
  border: 1px solid var(--border);
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 9.5px;
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  transition:
    background var(--dur) var(--ease),
    color var(--dur) var(--ease);
}
.icon-btn:hover {
  background: var(--surface-2);
  color: var(--text);
}
.lang-btn {
  width: auto;
  padding: 0 7px;
  gap: 5px;
}
.lang-code {
  font-size: 10px;
  font-weight: 600;
}
.user-button {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 8px 0 4px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
}
.user-button:hover {
  background: var(--surface-2);
  color: var(--text);
}
.avatar {
  width: 28px;
  height: 28px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  border: 1px solid color-mix(in srgb, var(--accent) 22%, transparent);
}
.user-name {
  font-size: 12px;
  font-weight: 500;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.content {
  flex: 1;
  min-width: 0;
}
.app-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
  padding: 12px 24px 20px;
  color: var(--text-3);
  font-size: 10.5px;
}
.app-footer a {
  color: var(--text-3);
}
.app-footer a:hover {
  color: var(--accent);
}
.dot-sep {
  opacity: 0.5;
}
.mobile-menu,
.mobile-nav {
  display: none;
}
.alerts-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.alerts-empty {
  padding: 22px 0 8px;
  text-align: center;
  color: var(--text-3);
  font-size: 12px;
}
.alert-list {
  list-style: none;
  margin: 0;
  padding: 4px 0 0;
  display: flex;
  flex-direction: column;
  max-height: 320px;
  overflow-y: auto;
}
.alert {
  display: flex;
  gap: 9px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.alert:last-child {
  border-bottom: 0;
}
.alert-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 5px;
  flex: none;
  background: var(--info);
}
.alert-dot.warning {
  background: var(--warning);
}
.alert-dot.critical,
.alert-dot.error {
  background: var(--danger);
}
.alert-copy {
  flex: 1;
  min-width: 0;
}
.alert-copy p {
  font-size: 12px;
  line-height: 1.45;
}
.alert-ack {
  border: 0;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  align-self: flex-start;
}
.alert-ack:hover {
  color: var(--success);
}
.drawer-nav {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.drawer-group {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.page-enter-active,
.page-leave-active {
  transition:
    opacity var(--dur) var(--ease),
    transform var(--dur) var(--ease);
}
.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
@media (max-width: 1023px) {
  .sidebar {
    display: none;
  }
  .main-column {
    margin-left: 0;
  }
  .mobile-menu {
    display: inline-flex;
  }
  .search-label,
  .user-name {
    display: none;
  }
  .topbar {
    padding: 0 14px;
    gap: 4px;
  }
  .breadcrumb {
    display: none;
  }
  .app-footer {
    padding-bottom: 86px;
  }
  .mobile-nav {
    position: fixed;
    z-index: 45;
    left: 12px;
    right: 12px;
    bottom: calc(10px + env(safe-area-inset-bottom));
    height: 62px;
    border-radius: 18px;
    display: flex;
    align-items: center;
    justify-content: space-around;
    padding: 0 6px;
    box-shadow: var(--shadow-2);
  }
  .mobile-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    color: var(--text-3);
    font-size: 9.5px;
    padding: 6px 0;
    border: 0;
    background: transparent;
    cursor: pointer;
    border-radius: 10px;
  }
  .mobile-item.active {
    color: var(--accent);
  }
}
@media (max-width: 767px) {
  .search-button {
    width: 34px;
    justify-content: center;
    padding: 0;
  }
  .search-button kbd,
  .lang-code {
    display: none;
  }
  .status-button {
    display: none;
  }
  .topbar-spacer {
    flex: 1;
  }
}
</style>
