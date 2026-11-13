<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NButton,
  NDatePicker,
  NDrawer,
  NDrawerContent,
  NDropdown,
  NInput,
  NModal,
  NPagination,
  NProgress,
  NSelect,
  useDialog,
  useMessage,
} from 'naive-ui'
import {
  ArrowDownToLine,
  CalendarClock,
  Ellipsis,
  KeyRound,
  Link2,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  UserRound,
  Users,
} from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import OErrorState from '@/components/OErrorState.vue'
import OTrafficChart from '@/components/OLazyChart.vue'
import OCopyButton from '@/components/OCopyButton.vue'
import OQrModal from '@/components/OQrModal.vue'
import { api } from '@/api'
import type { SubscriptionPayload, TrafficPoint, User } from '@/api/types'
import { formatBytes, formatDate, initials, percentOf, relativeTime } from '@/utils/format'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const users = ref<User[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const search = ref('')
const filter = ref('all')
const page = ref(1)
const pageSize = 50
const selected = ref<Set<string>>(new Set())
const busy = ref<string | null>(null)

const createOpen = ref(false)
const editing = ref<User | null>(null)
const form = ref({ name: '', quota: '', cycle: 'total', expires: null as number | null, note: '' })
const saving = ref(false)

const drawerOpen = ref(false)
const activeUser = ref<User | null>(null)
const usageSeries = ref<TrafficPoint[]>([])
const loadingUsage = ref(false)
let detailRequest = 0

const subscriptionOpen = ref(false)
const subscription = ref<SubscriptionPayload | null>(null)
const subscriptionUser = ref<User | null>(null)
const subscriptionRevealed = ref(false)
const createdPassword = ref<string | null>(null)
const qrOpen = ref(false)
const qrValue = ref('')

const filterOptions = computed(() => [
  { label: t('common.all'), value: 'all' },
  { label: t('common.online'), value: 'online' },
  { label: t('status.disabled'), value: 'disabled' },
  { label: t('status.expired'), value: 'expired' },
  { label: t('status.quota_exceeded'), value: 'quota_exceeded' },
])

const filtered = computed(() => {
  let list = users.value
  if (search.value.trim()) {
    const needle = search.value.trim().toLowerCase()
    list = list.filter(
      (user) =>
        user.name.toLowerCase().includes(needle) || user.note.toLowerCase().includes(needle),
    )
  }
  if (filter.value === 'online') list = list.filter((user) => user.online)
  else if (filter.value === 'disabled') list = list.filter((user) => !user.enabled)
  else if (filter.value !== 'all') list = list.filter((user) => user.status === filter.value)
  return list
})

const allSelected = computed(
  () => filtered.value.length > 0 && filtered.value.every((user) => selected.value.has(user.id)),
)

const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const paged = computed(() =>
  filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize),
)

const totalUsed = computed(() => users.value.reduce((sum, user) => sum + user.used_bytes, 0))

async function load() {
  loading.value = true
  try {
    users.value = (await api.users.list()).users
    error.value = null
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = { name: '', quota: '', cycle: 'total', expires: null, note: '' }
  createOpen.value = true
}

function openEdit(user: User) {
  editing.value = user
  form.value = {
    name: user.name,
    quota: user.quota_bytes ? formatBytes(user.quota_bytes, 0).replace(' ', '') : '',
    cycle: user.quota_cycle,
    expires: user.expires_at ? new Date(user.expires_at).getTime() : null,
    note: user.note,
  }
  createOpen.value = true
}

function parseBytes(value: string): number {
  const text = value.trim().toUpperCase()
  if (!text) return 0
  const match = text.match(/^([\d.]+)\s*(B|K|M|G|T|KB|MB|GB|TB|KIB|MIB|GIB|TIB)?$/)
  if (!match) return Number.NaN
  const amount = Number(match[1])
  const unit = (match[2] || 'B').replace('IB', '').replace('B', '')
  const factor: Record<string, number> = {
    '': 1,
    K: 1024,
    M: 1024 ** 2,
    G: 1024 ** 3,
    T: 1024 ** 4,
  }
  return Math.round(amount * (factor[unit] || 1))
}

async function save() {
  const quotaBytes = form.value.quota ? parseBytes(form.value.quota) : 0
  if (!form.value.name.trim() || Number.isNaN(quotaBytes)) {
    message.error(t('errors.validation'))
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      quota_bytes: quotaBytes,
      quota_cycle: form.value.cycle,
      expires_at: form.value.expires ? new Date(form.value.expires).toISOString() : null,
      note: form.value.note,
    }
    if (editing.value) {
      const result = await api.users.update(editing.value.id, payload)
      if (result.warning) message.warning(result.warning)
      message.success(t('users.updated'))
    } else {
      const result = await api.users.create(payload)
      if (result.warning) message.warning(result.warning)
      message.success(t('users.created'))
      subscription.value = result.subscription
      subscriptionUser.value = result.user
      subscriptionRevealed.value = true
      createdPassword.value = result.password_once
      subscriptionOpen.value = true
    }
    createOpen.value = false
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    saving.value = false
  }
}

async function toggleUser(user: User, enabled: boolean) {
  busy.value = user.id
  try {
    const result = await api.users.update(user.id, { enabled })
    if (result.warning) message.warning(result.warning)
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = null
  }
}

async function openDetail(user: User) {
  const request = ++detailRequest
  activeUser.value = user
  drawerOpen.value = true
  loadingUsage.value = true
  try {
    const [detail, usage] = await Promise.all([
      api.users.get(user.id),
      api.users.usage(user.id, 30),
    ])
    // A slower response for a previously-clicked user must not overwrite the
    // drawer that is now showing someone else.
    if (request !== detailRequest) return
    activeUser.value = detail.user
    usageSeries.value = usage.series
  } catch (err) {
    if (request === detailRequest) message.error((err as Error).message)
  } finally {
    if (request === detailRequest) loadingUsage.value = false
  }
}

async function openSubscription(user: User) {
  subscriptionUser.value = user
  subscriptionOpen.value = true
  subscription.value = null
  subscriptionRevealed.value = false
  createdPassword.value = null
  try {
    subscription.value = await api.users.subscription(user.id)
    subscriptionRevealed.value = !subscription.value.reveal_required
  } catch (err) {
    message.error((err as Error).message)
  }
}

async function revealSubscription() {
  if (!subscriptionUser.value) return
  try {
    subscription.value = await api.users.subscription(subscriptionUser.value.id, true)
    subscriptionRevealed.value = true
  } catch (err) {
    message.error((err as Error).message)
  }
}

function showQr(value: string) {
  qrValue.value = value
  qrOpen.value = true
}

function confirmRotate(user: User) {
  dialog.warning({
    title: t('users.rotate_credentials'),
    content: t('users.rotate_confirm'),
    positiveText: t('common.confirm'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        const result = await api.users.rotate(user.id)
        if (result.warning) message.warning(result.warning)
        message.success(t('users.credentials_rotated'))
        await load()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

function confirmReset(user: User) {
  dialog.warning({
    title: t('users.reset_usage'),
    content: t('users.reset_confirm'),
    positiveText: t('common.confirm'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.users.resetUsage(user.id)
        message.success(t('users.usage_reset'))
        await load()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

function confirmDelete(user: User) {
  dialog.error({
    title: t('common.delete'),
    content: t('users.delete_confirm', { name: user.name }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.users.remove(user.id)
        message.success(t('users.deleted'))
        drawerOpen.value = false
        await load()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

function toggleSelect(id: string) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleSelectAll() {
  if (allSelected.value) selected.value = new Set()
  else selected.value = new Set(filtered.value.map((user) => user.id))
}

async function bulk(action: 'enable' | 'disable' | 'delete' | 'export') {
  if (!selected.value.size) return
  try {
    const ids = [...selected.value]
    if (action === 'export') {
      const result = await api.users.bulk('export', ids)
      const blob = new Blob([JSON.stringify(result.exports ?? [], null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'ostium-users-export.json'
      link.click()
      URL.revokeObjectURL(url)
      message.success(t('users.exported'))
      return
    }
    if (action === 'delete') {
      const confirmed = await new Promise<boolean>((resolve, reject) => {
        dialog.error({
          title: t('common.delete'),
          content: t('common.delete_confirm'),
          positiveText: t('common.delete'),
          negativeText: t('common.cancel'),
          onPositiveClick: async () => {
            try {
              await api.users.bulk('delete', ids)
              resolve(true)
            } catch (err) {
              reject(err)
            }
          },
          onNegativeClick: () => resolve(false),
        })
      })
      if (!confirmed) return
    } else {
      await api.users.bulk(action, ids)
    }
    message.success(t('users.updated'))
    selected.value = new Set()
    await load()
  } catch (err) {
    message.error((err as Error).message)
  }
}

function rowOptions(user: User) {
  return [
    { label: t('users.subscription'), key: 'subscription' },
    { label: t('users.rotate_credentials'), key: 'rotate' },
    { label: t('users.reset_usage'), key: 'reset' },
    { label: user.enabled ? t('common.disable') : t('common.enable'), key: 'toggle' },
    { type: 'divider', key: 'divider' },
    { label: t('common.delete'), key: 'delete' },
  ]
}

function onRowAction(user: User, key: string) {
  if (key === 'subscription') void openSubscription(user)
  else if (key === 'rotate') confirmRotate(user)
  else if (key === 'reset') confirmReset(user)
  else if (key === 'toggle') void toggleUser(user, !user.enabled)
  else if (key === 'delete') confirmDelete(user)
}

function statusLabel(user: User): string {
  if (user.online) return t('status.online')
  if (!user.enabled)
    return user.disabled_reason ? t(`status.${user.disabled_reason}`) : t('status.disabled')
  if (user.status === 'expired') return t('status.expired')
  if (user.status === 'quota_exceeded') return t('status.quota_exceeded')
  return t('status.active')
}

watch(
  () => route.query.create,
  (value) => {
    if (value === '1' && !createOpen.value) openCreate()
    if (value === '1') void router.replace({ query: { ...route.query, create: undefined } })
  },
)

watch(
  () => route.query.focus,
  async (value) => {
    if (typeof value === 'string') {
      const user = users.value.find((item) => item.id === value)
      if (user) await openDetail(user)
      void router.replace({ query: { ...route.query, focus: undefined } })
    }
  },
)

watch([search, filter, page], () => {
  const query: Record<string, string> = { ...(route.query as Record<string, string>) }
  if (search.value.trim()) query.q = search.value.trim()
  else delete query.q
  if (filter.value !== 'all') query.filter = filter.value
  else delete query.filter
  if (page.value > 1) query.page = String(page.value)
  else delete query.page
  void router.replace({ query })
})

watch(filtered, () => {
  if (page.value > pageCount.value) page.value = pageCount.value
})

onMounted(async () => {
  if (typeof route.query.q === 'string') search.value = route.query.q
  if (typeof route.query.filter === 'string') filter.value = route.query.filter
  if (typeof route.query.page === 'string') page.value = Math.max(1, Number(route.query.page) || 1)
  await load()
  if (route.query.create === '1') openCreate()
})
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('users.title')" :subtitle="t('users.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton type="primary" @click="openCreate">
          <template #icon><Plus :size="16" /></template>
          {{ t('users.add') }}
        </NButton>
      </template>
    </OPageHeader>

    <div class="summary-row">
      <div class="summary">
        <Users :size="17" />
        <strong>{{ users.length }}</strong>
        <span>{{ t('users.title') }}</span>
      </div>
      <div class="summary">
        <ArrowDownToLine :size="17" />
        <strong>{{ formatBytes(totalUsed) }}</strong>
        <span>{{ t('common.total') }}</span>
      </div>
      <div class="summary">
        <CalendarClock :size="17" />
        <strong>{{ users.filter((user) => user.online).length }}</strong>
        <span>{{ t('common.online') }}</span>
      </div>
    </div>

    <div class="toolbar">
      <NInput
        v-model:value="search"
        clearable
        :placeholder="t('common.search')"
        data-search
        class="search"
      >
        <template #prefix><Search :size="15" /></template>
      </NInput>
      <NSelect v-model:value="filter" :options="filterOptions" class="filter" />
      <div class="spacer" />
      <span v-if="selected.size" class="o-small o-muted">{{
        t('users.selected', { count: selected.size })
      }}</span>
      <NButton v-if="selected.size" size="small" secondary @click="bulk('enable')">{{
        t('users.bulk_enable')
      }}</NButton>
      <NButton v-if="selected.size" size="small" secondary @click="bulk('disable')">{{
        t('users.bulk_disable')
      }}</NButton>
      <NButton v-if="selected.size" size="small" secondary @click="bulk('export')">{{
        t('users.bulk_export')
      }}</NButton>
      <NButton v-if="selected.size" size="small" secondary type="error" @click="bulk('delete')">{{
        t('users.bulk_delete')
      }}</NButton>
    </div>

    <OErrorState v-if="error" :message="error" @retry="load" />

    <div v-else-if="!loading && !filtered.length" class="o-card">
      <OEmptyState :title="t('users.empty_title')" :description="t('users.empty_desc')">
        <NButton type="primary" @click="openCreate">
          <template #icon><Plus :size="15" /></template>
          {{ t('users.add') }}
        </NButton>
      </OEmptyState>
    </div>

    <div v-else class="table-card o-card">
      <div class="table-head">
        <label class="check">
          <input type="checkbox" :checked="allSelected" @change="toggleSelectAll" />
        </label>
        <span class="col-user">{{ t('users.name') }}</span>
        <span class="col-status">{{ t('users.status') }}</span>
        <span class="col-usage">{{ t('common.usage') }}</span>
        <span class="col-expiry">{{ t('users.expires') }}</span>
        <span class="col-seen">{{ t('users.last_seen') }}</span>
        <span class="col-actions" />
      </div>
      <div
        v-for="user in paged"
        :key="user.id"
        class="table-row"
        :class="{ selected: selected.has(user.id) }"
        @click="openDetail(user)"
      >
        <label class="check" @click.stop>
          <input type="checkbox" :checked="selected.has(user.id)" @change="toggleSelect(user.id)" />
        </label>
        <div class="col-user user-cell">
          <span class="avatar">{{ initials(user.name) }}</span>
          <div class="user-copy">
            <strong>{{ user.name }}</strong>
            <span class="o-micro o-subtle">{{ user.note || user.uuid.slice(0, 8) }}</span>
          </div>
        </div>
        <div class="col-status" @click.stop>
          <OStatusPill
            :status="user.online ? 'online' : !user.enabled ? 'disabled' : user.status"
            :label="statusLabel(user)"
            size="sm"
          />
        </div>
        <div class="col-usage usage-cell">
          <template v-if="user.quota_bytes">
            <NProgress
              type="line"
              :percentage="percentOf(user.used_bytes, user.quota_bytes)"
              :show-indicator="false"
              :status="percentOf(user.used_bytes, user.quota_bytes) > 90 ? 'error' : 'default'"
              :aria-label="user.name"
              size="small"
            />
            <span class="o-micro o-subtle"
              >{{ formatBytes(user.used_bytes) }} / {{ formatBytes(user.quota_bytes) }}</span
            >
          </template>
          <span v-else class="o-mono used">{{ formatBytes(user.used_bytes) }}</span>
        </div>
        <div class="col-expiry o-small o-muted">
          {{ user.expires_at ? formatDate(user.expires_at, locale) : t('common.never') }}
        </div>
        <div class="col-seen o-small o-subtle">{{ relativeTime(user.last_seen_at, locale) }}</div>
        <div class="col-actions" @click.stop>
          <NDropdown
            :options="rowOptions(user)"
            trigger="click"
            @select="(key: string) => onRowAction(user, key)"
          >
            <NButton size="tiny" quaternary circle :loading="busy === user.id">
              <template #icon><Ellipsis :size="16" /></template>
            </NButton>
          </NDropdown>
        </div>
      </div>
    </div>

    <div v-if="filtered.length > pageSize" class="pagination">
      <NPagination v-model:page="page" :page-count="pageCount" :page-size="pageSize" />
    </div>

    <NModal
      v-model:show="createOpen"
      preset="card"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ editing ? t('users.edit') : t('users.add') }}</template>
      <div class="form">
        <label class="field">
          <span>{{ t('users.name') }}</span>
          <NInput v-model:value="form.name" :disabled="!!editing" :placeholder="t('users.name')" />
          <small class="o-subtle">{{ t('users.name_hint') }}</small>
        </label>
        <div class="form-grid">
          <label class="field">
            <span>{{ t('users.quota') }}</span>
            <NInput v-model:value="form.quota" placeholder="50G" />
            <small class="o-subtle">{{ t('users.quota_hint') }}</small>
          </label>
          <label class="field">
            <span>{{ t('users.quota_cycle') }}</span>
            <NSelect
              v-model:value="form.cycle"
              :options="[
                { label: t('users.cycle_total'), value: 'total' },
                { label: t('users.cycle_monthly'), value: 'monthly' },
              ]"
            />
          </label>
        </div>
        <label class="field">
          <span>{{ t('users.expires') }}</span>
          <NDatePicker v-model:value="form.expires" type="datetime" clearable style="width: 100%" />
          <small class="o-subtle">{{ t('users.expires_hint') }}</small>
        </label>
        <label class="field">
          <span>{{ t('users.note') }}</span>
          <NInput
            v-model:value="form.note"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
          />
        </label>
      </div>
      <template #footer>
        <div class="modal-actions">
          <NButton secondary @click="createOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="saving" @click="save">{{ t('common.save') }}</NButton>
        </div>
      </template>
    </NModal>

    <NDrawer v-model:show="drawerOpen" :width="520" placement="right">
      <NDrawerContent v-if="activeUser" closable>
        <template #header>
          <div class="drawer-header">
            <span class="avatar large">{{ initials(activeUser.name) }}</span>
            <div>
              <strong>{{ activeUser.name }}</strong>
              <OStatusPill
                :status="
                  activeUser.online ? 'online' : activeUser.enabled ? activeUser.status : 'disabled'
                "
                :label="statusLabel(activeUser)"
                size="sm"
              />
            </div>
          </div>
        </template>
        <div class="drawer-body">
          <div class="detail-grid">
            <div>
              <span>{{ t('users.used') }}</span><strong>{{
                formatBytes(activeUser.used_bytes)
              }}</strong>
            </div>
            <div>
              <span>{{ t('users.quota') }}</span><strong>{{
                activeUser.quota_bytes ? formatBytes(activeUser.quota_bytes) : t('common.unlimited')
              }}</strong>
            </div>
            <div>
              <span>{{ t('users.expires') }}</span><strong>{{
                activeUser.expires_at
                  ? formatDate(activeUser.expires_at, locale)
                  : t('common.never')
              }}</strong>
            </div>
            <div>
              <span>{{ t('users.last_seen') }}</span><strong>{{
                relativeTime(activeUser.last_seen_at, locale)
              }}</strong>
            </div>
          </div>

          <div class="drawer-actions">
            <NButton size="small" secondary @click="openSubscription(activeUser)">
              <template #icon><Link2 :size="14" /></template>
              {{ t('users.subscription') }}
            </NButton>
            <NButton size="small" secondary @click="openEdit(activeUser)">
              <template #icon><UserRound :size="14" /></template>
              {{ t('common.edit') }}
            </NButton>
            <NButton size="small" secondary @click="confirmRotate(activeUser)">
              <template #icon><KeyRound :size="14" /></template>
              {{ t('common.rotate') }}
            </NButton>
            <NButton size="small" secondary @click="confirmReset(activeUser)">
              <template #icon><RotateCcw :size="14" /></template>
              {{ t('users.reset_usage') }}
            </NButton>
          </div>

          <section class="usage-block">
            <h3>{{ t('users.usage_chart') }}</h3>
            <div v-if="loadingUsage" class="loading">…</div>
            <OEmptyState
              v-else-if="!usageSeries.length"
              compact
              :title="t('users.no_usage')"
              :description="t('users.no_usage')"
            />
            <OTrafficChart v-else :series="usageSeries" :height="200" />
          </section>

          <section class="meta-block">
            <h3>{{ t('common.details') }}</h3>
            <div class="meta-row">
              <span>UUID</span><code class="o-mono">{{ activeUser.uuid }}</code
              ><OCopyButton :value="activeUser.uuid" size="tiny" />
            </div>
            <div class="meta-row">
              <span>{{ t('users.quota_cycle') }}</span><strong>{{ activeUser.quota_cycle }}</strong>
            </div>
            <div class="meta-row">
              <span>{{ t('common.created_at') }}</span><strong>{{
                formatDate(activeUser.created_at, locale)
              }}</strong>
            </div>
            <div class="meta-row">
              <span>{{ t('common.note') }}</span><strong>{{ activeUser.note || '—' }}</strong>
            </div>
          </section>

          <div class="danger-zone">
            <NButton type="error" secondary block @click="confirmDelete(activeUser)">
              <template #icon><Trash2 :size="15" /></template>
              {{ t('common.delete') }}
            </NButton>
          </div>
        </div>
      </NDrawerContent>
    </NDrawer>

    <NModal
      v-model:show="subscriptionOpen"
      preset="card"
      :style="{ width: 'min(640px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('subscriptions.title') }} · {{ subscriptionUser?.name }}</template>
      <div v-if="!subscription" class="loading">…</div>
      <div v-else class="sub-body">
        <div v-if="createdPassword" class="password-once">
          <strong>{{ t('users.password_once') }}</strong>
          <code>{{ createdPassword }}</code>
          <OCopyButton :value="createdPassword" size="small" />
        </div>
        <div class="sub-warning">{{ t('subscriptions.token_warning') }}</div>
        <div v-if="!subscriptionRevealed" class="sub-locked">
          <p>{{ t('subscriptions.reveal_hint') }}</p>
          <NButton type="primary" @click="revealSubscription">
            {{ t('subscriptions.reveal') }}
          </NButton>
        </div>
        <template v-else>
          <div class="sub-grid">
            <div v-for="format in subscription.formats || []" :key="format.id" class="sub-card">
              <div>
                <strong>{{ format.name }}</strong>
                <span class="o-micro o-subtle">{{ format.id }}</span>
              </div>
              <div class="sub-actions">
                <OCopyButton :value="format.url" size="small" />
                <NButton size="small" secondary @click="showQr(format.url)">
                  <template #icon><Link2 :size="14" /></template>
                  {{ t('subscriptions.qr') }}
                </NButton>
              </div>
            </div>
          </div>
          <p class="o-small o-muted">{{ t('subscriptions.scan_hint') }}</p>
        </template>
      </div>
    </NModal>

    <OQrModal
      v-model:show="qrOpen"
      :value="qrValue"
      :title="t('subscriptions.qr')"
      :description="t('subscriptions.scan_hint')"
    />
  </div>
</template>

<style scoped>
.summary-row {
  display: flex;
  gap: 26px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.summary {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text-3);
  font-size: 12px;
}
.summary strong {
  color: var(--text);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.search {
  max-width: 300px;
}
.filter {
  width: 150px;
}
.spacer {
  flex: 1;
}
.pagination {
  display: flex;
  justify-content: flex-end;
  padding: 12px 4px;
}
.table-card {
  overflow: hidden;
}
.table-head,
.table-row {
  display: grid;
  grid-template-columns: 40px minmax(180px, 1.35fr) 120px minmax(160px, 1.1fr) 140px 120px 44px;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
}
.table-head {
  height: 44px;
  color: var(--text-3);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface-2) 55%, transparent);
}
.table-row {
  min-height: 62px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.table-row:last-child {
  border-bottom: 0;
}
.table-row:hover,
.table-row.selected {
  background: color-mix(in srgb, var(--accent) 4%, transparent);
}
.check input {
  width: 15px;
  height: 15px;
  accent-color: var(--accent);
}
.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  flex: none;
  display: grid;
  place-items: center;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 10.5px;
  font-weight: 700;
  border: 1px solid color-mix(in srgb, var(--accent) 18%, transparent);
}
.avatar.large {
  width: 42px;
  height: 42px;
  font-size: 13px;
}
.user-copy {
  min-width: 0;
}
.user-copy strong {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.usage-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.used {
  font-size: 12px;
  color: var(--text-2);
}
.form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field > span {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
}
.field small {
  line-height: 1.5;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.drawer-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.drawer-header strong {
  display: block;
  font-size: 15px;
  margin-bottom: 3px;
}
.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.detail-grid div {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.detail-grid span {
  color: var(--text-3);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.detail-grid strong {
  font-size: 12.5px;
  font-weight: 600;
}
.drawer-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.usage-block h3,
.meta-block h3 {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-2);
}
.loading {
  padding: 30px;
  text-align: center;
  color: var(--text-3);
}
.meta-block {
  border-top: 1px solid var(--border);
  padding-top: 14px;
}
.meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
  font-size: 11.5px;
}
.meta-row span {
  width: 90px;
  flex: none;
  color: var(--text-3);
}
.meta-row code,
.meta-row strong {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--text-2);
}
.danger-zone {
  margin-top: 8px;
}
.sub-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.sub-warning {
  padding: 9px 11px;
  border-radius: 9px;
  border: 1px solid color-mix(in srgb, var(--warning) 26%, transparent);
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 11.5px;
}
.sub-locked {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
  padding: 22px;
  border: 1px dashed var(--border);
  border-radius: 11px;
  color: var(--text-3);
  text-align: center;
}
.password-once {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
  background: color-mix(in srgb, var(--success) 10%, transparent);
  font-size: 11.5px;
}
.password-once code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
}
.sub-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.sub-card {
  padding: 12px;
  border-radius: 11px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sub-card strong {
  display: block;
  font-size: 12px;
}
.sub-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
@media (max-width: 1100px) {
  .table-head,
  .table-row {
    grid-template-columns: 34px minmax(150px, 1.2fr) 100px minmax(130px, 1fr) 100px 36px;
  }
  .col-seen {
    display: none;
  }
}
@media (max-width: 767px) {
  .table-head {
    display: none;
  }
  .table-row {
    grid-template-columns: 32px 1fr auto;
    gap: 8px;
    padding: 12px;
  }
  .col-status,
  .col-expiry,
  .col-seen {
    display: none;
  }
  .col-usage {
    grid-column: 2 / 3;
  }
  .col-actions {
    grid-column: 3;
  }
  .form-grid,
  .detail-grid,
  .sub-grid {
    grid-template-columns: 1fr;
  }
}
</style>
