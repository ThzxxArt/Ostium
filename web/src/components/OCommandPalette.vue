<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NModal, NInput, NSpin } from 'naive-ui'
import Fuse from 'fuse.js'
import {
  ArrowRight,
  CornerDownLeft,
  Languages,
  ListChecks,
  LogOut,
  Moon,
  Search,
  Sun,
  Users,
  Keyboard,
} from '@lucide/vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api'
import type { User } from '@/api/types'
import { clientNav, serverNav, type NavItem } from '@/router/nav'

const app = useAppStore()
const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n()

const query = ref('')
const selected = ref(0)
const users = ref<User[]>([])
const loadingUsers = ref(false)
const inputRef = ref<InstanceType<typeof NInput> | null>(null)

interface PaletteItem {
  id: string
  label: string
  hint?: string
  group: string
  keywords: string
  icon?: unknown
  action: () => void | Promise<unknown>
}

const navItems = computed<NavItem[]>(() => {
  const groups = auth.isServer ? serverNav : clientNav
  return groups.flatMap((group) => group.items)
})

const recent = ref<string[]>([])
try {
  recent.value = JSON.parse(localStorage.getItem('ostium.recent') || '[]') as string[]
} catch {
  recent.value = []
}

function remember(id: string) {
  recent.value = [id, ...recent.value.filter((item) => item !== id)].slice(0, 5)
  try {
    localStorage.setItem('ostium.recent', JSON.stringify(recent.value))
  } catch {
    /* ignore */
  }
}

const allItems = computed<PaletteItem[]>(() => {
  const pages: PaletteItem[] = navItems.value.map((item) => ({
    id: `page:${item.key}`,
    label: t(item.labelKey),
    group: t('command.pages'),
    keywords: `${item.key} ${item.path} ${(item.keywords || []).join(' ')}`,
    icon: item.icon,
    action: () => router.push(item.path),
  }))
  const actions: PaletteItem[] = [
    {
      id: 'action:theme',
      label: t('command.theme'),
      group: t('command.actions'),
      keywords: 'theme dark light appearance',
      icon: app.isDark ? Sun : Moon,
      action: () => app.toggleTheme(),
    },
    {
      id: 'action:language',
      label: t('command.language'),
      group: t('command.actions'),
      keywords: 'language english chinese locale i18n',
      icon: Languages,
      action: () => app.toggleLanguage(),
    },
    {
      id: 'action:jobs',
      label: t('nav.jobs'),
      group: t('command.actions'),
      keywords: 'jobs tasks progress',
      icon: ListChecks,
      action: () => (app.jobDrawerOpen = true),
    },
    {
      id: 'action:shortcuts',
      label: t('command.shortcuts'),
      group: t('command.actions'),
      keywords: 'keyboard help shortcuts',
      icon: Keyboard,
      action: () => (app.shortcutsOpen = true),
    },
    {
      id: 'action:logout',
      label: t('command.logout'),
      group: t('command.actions'),
      keywords: 'logout sign out',
      icon: LogOut,
      action: async () => {
        await auth.logout()
        await router.push('/login')
      },
    },
  ]
  const userItems: PaletteItem[] = users.value.map((user) => ({
    id: `user:${user.id}`,
    label: user.name,
    hint: user.status,
    group: t('command.users'),
    keywords: `user ${user.name}`,
    icon: Users,
    action: () => router.push(`/users?focus=${user.id}`),
  }))
  return [...pages, ...actions, ...userItems]
})

const fuse = computed(
  () => new Fuse(allItems.value, { keys: ['label', 'keywords'], threshold: 0.35 }),
)

const results = computed<PaletteItem[]>(() => {
  if (!query.value.trim()) {
    const map = new Map(allItems.value.map((item) => [item.id, item]))
    const recentItems = recent.value.map((id) => map.get(id)).filter(Boolean) as PaletteItem[]
    const fallback = allItems.value.filter((item) => item.group === t('command.pages')).slice(0, 6)
    return [...recentItems, ...fallback.filter((item) => !recent.value.includes(item.id))].slice(
      0,
      10,
    )
  }
  return fuse.value
    .search(query.value)
    .map((result) => result.item)
    .slice(0, 12)
})

watch(
  () => app.commandOpen,
  async (open) => {
    if (open) {
      query.value = ''
      selected.value = 0
      await nextTick()
      inputRef.value?.focus()
      if (auth.isServer && !users.value.length) {
        loadingUsers.value = true
        try {
          users.value = (await api.users.list()).users
        } catch {
          /* users are optional in the palette */
        } finally {
          loadingUsers.value = false
        }
      }
    }
  },
)

watch(query, () => (selected.value = 0))

function choose(item: PaletteItem | undefined) {
  if (!item) return
  remember(item.id)
  app.commandOpen = false
  void item.action()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    selected.value = (selected.value + 1) % Math.max(1, results.value.length)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    selected.value = (selected.value - 1 + results.value.length) % Math.max(1, results.value.length)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    choose(results.value[selected.value])
  }
}
</script>

<template>
  <NModal v-model:show="app.commandOpen" :mask-closable="true" class="palette-modal">
    <div class="palette" role="dialog" aria-label="Command palette">
      <div class="search">
        <Search :size="18" :stroke-width="1.7" />
        <NInput
          ref="inputRef"
          v-model:value="query"
          :placeholder="t('command.placeholder')"
          :bordered="false"
          size="large"
          @keydown="onKeydown"
        />
        <kbd>Esc</kbd>
      </div>
      <div class="results o-scroll">
        <div v-if="loadingUsers" class="loading"><NSpin size="small" /></div>
        <template v-for="(item, index) in results" :key="item.id">
          <p v-if="index === 0 || results[index - 1].group !== item.group" class="group">
            {{ item.group }}
          </p>
          <button
            type="button"
            class="item"
            :class="{ active: index === selected }"
            @mouseenter="selected = index"
            @click="choose(item)"
          >
            <span class="icon"><component :is="item.icon" :size="17" :stroke-width="1.7" /></span>
            <span class="label">{{ item.label }}</span>
            <span v-if="item.hint" class="hint">{{ item.hint }}</span>
            <CornerDownLeft v-if="index === selected" :size="14" class="enter" />
            <ArrowRight v-else :size="14" class="arrow" />
          </button>
        </template>
        <p v-if="!results.length" class="empty">{{ t('command.no_results') }}</p>
      </div>
      <footer class="footer">
        <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
        <span><kbd>↵</kbd> open</span>
        <span><kbd>Esc</kbd> close</span>
      </footer>
    </div>
  </NModal>
</template>

<style scoped>
:global(.palette-modal) {
  width: min(640px, calc(100vw - 32px));
  margin-top: 12vh;
}
.palette {
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-strong);
  background: color-mix(in srgb, var(--surface-solid) 94%, transparent);
  backdrop-filter: blur(22px);
  box-shadow: var(--shadow-3);
  overflow: hidden;
}
.search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  color: var(--text-3);
}
.search :deep(.n-input) {
  flex: 1;
  background: transparent;
}
kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 20px;
  padding: 0 5px;
  border-radius: 5px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 10px;
  font-family: var(--font-mono);
}
.results {
  max-height: min(56vh, 440px);
  overflow-y: auto;
  padding: 8px;
}
.group {
  padding: 10px 12px 6px;
  font-size: 10.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-3);
}
.item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  text-align: left;
}
.item.active {
  background: var(--accent-soft);
  color: var(--accent);
}
.icon {
  display: inline-flex;
  color: currentColor;
  opacity: 0.9;
}
.label {
  flex: 1;
  font-size: 13px;
}
.hint {
  font-size: 11px;
  color: var(--text-3);
}
.enter,
.arrow {
  color: var(--text-3);
}
.empty {
  padding: 28px;
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
}
.loading {
  display: flex;
  justify-content: center;
  padding: 6px;
}
.footer {
  display: flex;
  gap: 18px;
  padding: 10px 16px;
  border-top: 1px solid var(--border);
  color: var(--text-3);
  font-size: 10.5px;
}
.footer span {
  display: flex;
  align-items: center;
  gap: 5px;
}
</style>
