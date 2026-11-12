<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, useDialog, useMessage } from 'naive-ui'
import { Link2, QrCode, RefreshCw, RotateCcw, Search, ShieldAlert } from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OCopyButton from '@/components/OCopyButton.vue'
import OQrModal from '@/components/OQrModal.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import OErrorState from '@/components/OErrorState.vue'
import { api } from '@/api'
import type { SubscriptionPayload, User } from '@/api/types'
import { formatBytes, initials, relativeTime } from '@/utils/format'

const { t, locale } = useI18n()
const message = useMessage()
const dialog = useDialog()

const users = ref<User[]>([])
const selectedId = ref<string | null>(null)
const subscription = ref<SubscriptionPayload | null>(null)
const loading = ref(true)
const loadingSub = ref(false)
const error = ref<string | null>(null)
const search = ref('')
const qrOpen = ref(false)
const qrValue = ref('')

const filtered = computed(() => {
  if (!search.value.trim()) return users.value
  const needle = search.value.toLowerCase()
  return users.value.filter((user) => user.name.toLowerCase().includes(needle))
})

const selectedUser = computed(
  () => users.value.find((user) => user.id === selectedId.value) || null,
)

async function load() {
  loading.value = true
  try {
    const [overview, userList] = await Promise.all([api.subscriptions.overview(), api.users.list()])
    users.value = userList.users
    if (!selectedId.value && users.value.length) selectedId.value = users.value[0].id
    if (selectedId.value) await loadSubscription(selectedId.value)
    error.value = null
    void overview
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

async function loadSubscription(id: string) {
  loadingSub.value = true
  try {
    subscription.value = await api.users.subscription(id)
  } catch (err) {
    subscription.value = null
    message.error((err as Error).message)
  } finally {
    loadingSub.value = false
  }
}

async function selectUser(user: User) {
  selectedId.value = user.id
  await loadSubscription(user.id)
}

function showQr(value: string) {
  qrValue.value = value
  qrOpen.value = true
}

function confirmRotate() {
  if (!selectedUser.value) return
  dialog.warning({
    title: t('subscriptions.rotate'),
    content: t('subscriptions.rotate_confirm'),
    positiveText: t('common.confirm'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        subscription.value = await api.users.rotateSubscription(selectedUser.value!.id)
        message.success(t('subscriptions.rotate'))
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

onMounted(load)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('subscriptions.title')" :subtitle="t('subscriptions.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
      </template>
    </OPageHeader>

    <OErrorState v-if="error" :message="error" @retry="load" />

    <div v-else-if="!loading && !users.length" class="o-card">
      <OEmptyState :title="t('users.empty_title')" :description="t('subscriptions.no_users')" />
    </div>

    <div v-else class="layout">
      <aside class="user-list o-card">
        <div class="list-head">
          <span class="o-micro o-subtle">{{ t('subscriptions.select_user') }}</span>
          <NInput v-model:value="search" size="small" clearable :placeholder="t('common.search')">
            <template #prefix><Search :size="14" /></template>
          </NInput>
        </div>
        <button
          v-for="user in filtered"
          :key="user.id"
          type="button"
          class="user-item"
          :class="{ active: selectedId === user.id }"
          @click="selectUser(user)"
        >
          <span class="avatar">{{ initials(user.name) }}</span>
          <span class="user-copy">
            <strong>{{ user.name }}</strong>
            <span class="o-micro o-subtle"
              >{{ formatBytes(user.used_bytes) }} ·
              {{ relativeTime(user.last_seen_at, locale) }}</span
            >
          </span>
          <OStatusPill
            :status="user.online ? 'online' : user.enabled ? 'active' : 'disabled'"
            size="sm"
          />
        </button>
        <div v-if="!filtered.length" class="list-empty">{{ t('common.no_data') }}</div>
      </aside>

      <section class="detail o-card">
        <div v-if="loadingSub" class="loading">…</div>
        <template v-else-if="subscription && selectedUser">
          <div class="detail-head">
            <div>
              <p class="o-kicker">{{ t('subscriptions.title') }}</p>
              <h2>{{ selectedUser.name }}</h2>
              <p class="o-muted o-small">{{ t('subscriptions.scan_hint') }}</p>
            </div>
            <NButton size="small" secondary @click="confirmRotate">
              <template #icon><RotateCcw :size="14" /></template>
              {{ t('subscriptions.rotate') }}
            </NButton>
          </div>

          <div class="token-warning">
            <ShieldAlert :size="15" />
            <span>{{ t('subscriptions.token_warning') }}</span>
          </div>

          <div class="formats">
            <article v-for="format in subscription.formats" :key="format.id" class="format-card">
              <div class="format-head">
                <span class="format-icon"><Link2 :size="17" /></span>
                <div>
                  <strong>{{ format.name }}</strong>
                  <span class="o-micro o-subtle">{{ format.id }}</span>
                </div>
              </div>
              <code class="url o-truncate">{{ format.url }}</code>
              <div class="format-actions">
                <OCopyButton :value="format.url" size="small" :label="t('common.copy')" />
                <NButton size="small" secondary @click="showQr(format.url)">
                  <template #icon><QrCode :size="14" /></template>
                  {{ t('subscriptions.qr') }}
                </NButton>
              </div>
            </article>
          </div>

          <div v-if="subscription.links.length" class="links">
            <h3>{{ t('subscriptions.links') }}</h3>
            <div v-for="(link, index) in subscription.links" :key="index" class="link-row">
              <code class="o-truncate">{{ link }}</code>
              <OCopyButton :value="link" size="tiny" />
            </div>
          </div>
        </template>
        <OEmptyState
          v-else
          :title="t('common.no_data')"
          :description="t('subscriptions.no_users')"
        />
      </section>
    </div>

    <OQrModal
      v-model:show="qrOpen"
      :value="qrValue"
      :title="t('subscriptions.qr')"
      :description="t('subscriptions.scan_hint')"
    />
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
.user-list {
  padding: 10px;
  position: sticky;
  top: calc(var(--topbar-height) + 20px);
  max-height: calc(100vh - var(--topbar-height) - 60px);
  overflow-y: auto;
}
.list-head {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 6px 6px 10px;
}
.user-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  text-align: left;
}
.user-item:hover {
  background: var(--surface-2);
}
.user-item.active {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 22%, transparent);
}
.avatar {
  width: 32px;
  height: 32px;
  flex: none;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: var(--surface-2);
  color: var(--accent);
  font-size: 10px;
  font-weight: 700;
}
.user-copy {
  flex: 1;
  min-width: 0;
}
.user-copy strong {
  display: block;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.list-empty {
  padding: 20px;
  text-align: center;
  color: var(--text-3);
  font-size: 11.5px;
}
.detail {
  padding: 22px;
  min-height: 520px;
}
.loading {
  padding: 40px;
  text-align: center;
  color: var(--text-3);
}
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}
.detail-head h2 {
  font-size: 23px;
  letter-spacing: -0.03em;
  margin-top: 4px;
}
.detail-head p {
  margin-top: 4px;
}
.token-warning {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 18px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--warning) 26%, transparent);
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 11.5px;
}
.formats {
  margin-top: 18px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.format-card {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 13px;
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.format-head {
  display: flex;
  align-items: center;
  gap: 9px;
}
.format-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: var(--accent);
  background: var(--accent-soft);
}
.format-head strong {
  display: block;
  font-size: 12px;
}
.url {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-3);
  padding: 7px 9px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg) 45%, transparent);
  border: 1px solid var(--border);
}
.format-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.links {
  margin-top: 22px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.links h3 {
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 8px;
}
.link-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
}
.link-row code {
  flex: 1;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-3);
}
@media (max-width: 1000px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .user-list {
    position: static;
    max-height: none;
  }
  .formats {
    grid-template-columns: 1fr;
  }
}
</style>
