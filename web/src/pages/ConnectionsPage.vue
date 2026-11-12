<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, NSwitch, useMessage } from 'naive-ui'
import { Ban, Cable, Pause, Play, RefreshCw, Search, XCircle } from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { ConnectionEntry } from '@/api/types'
import { formatBytes, formatDuration } from '@/utils/format'

const { t } = useI18n()
const message = useMessage()

const connections = ref<ConnectionEntry[]>([])
const uploadTotal = ref(0)
const downloadTotal = ref(0)
const unavailable = ref(false)
const loading = ref(true)
const paused = ref(false)
const search = ref('')
let timer: number | null = null

const filtered = computed(() => {
  if (!search.value.trim()) return connections.value
  const needle = search.value.toLowerCase()
  return connections.value.filter((item) => {
    const meta = item.metadata || {}
    return [meta.user, meta.host, meta.destinationIP, meta.processPath, item.rule]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(needle))
  })
})

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const data = await api.stats.connections(search.value || undefined)
    connections.value = data.connections
    uploadTotal.value = data.upload_total
    downloadTotal.value = data.download_total
    unavailable.value = data.unavailable
  } catch (err) {
    if (!silent) message.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function closeConnection(item: ConnectionEntry) {
  try {
    await api.stats.closeConnection(item.id)
    message.success(t('connections.close'))
    await load(true)
  } catch (err) {
    message.error((err as Error).message)
  }
}

async function closeAll() {
  try {
    await api.stats.closeAll()
    message.success(t('connections.close_all'))
    await load(true)
  } catch (err) {
    message.error((err as Error).message)
  }
}

function togglePause() {
  paused.value = !paused.value
  if (paused.value && timer !== null) {
    clearInterval(timer)
    timer = null
  } else if (!paused.value) {
    startTimer()
  }
}

function startTimer() {
  if (timer !== null) clearInterval(timer)
  timer = window.setInterval(() => {
    if (!paused.value) void load(true)
  }, 3000)
}

function duration(item: ConnectionEntry): string {
  const start = new Date(item.start).getTime()
  if (Number.isNaN(start)) return '—'
  return formatDuration((Date.now() - start) / 1000)
}

onMounted(() => {
  void load()
  startTimer()
})
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer)
})
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('connections.title')" :subtitle="t('connections.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load()">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton type="error" secondary :disabled="!connections.length" @click="closeAll">
          <template #icon><XCircle :size="15" /></template>
          {{ t('connections.close_all') }}
        </NButton>
      </template>
    </OPageHeader>

    <div class="summary">
      <div>
        <span>{{ t('common.total') }}</span><strong>{{ connections.length }}</strong>
      </div>
      <div>
        <span>{{ t('common.up') }}</span><strong>{{ formatBytes(uploadTotal) }}</strong>
      </div>
      <div>
        <span>{{ t('common.down') }}</span><strong>{{ formatBytes(downloadTotal) }}</strong>
      </div>
      <div class="pause">
        <span>{{ paused ? t('connections.paused') : t('common.live') }}</span>
        <NSwitch :value="paused" size="small" @update:value="togglePause">
          <template #checked><Pause :size="11" /></template>
          <template #unchecked><Play :size="11" /></template>
        </NSwitch>
      </div>
    </div>

    <div class="toolbar">
      <NInput
        v-model:value="search"
        clearable
        :placeholder="t('common.search')"
        data-search
        @update:value="load(true)"
      >
        <template #prefix><Search :size="15" /></template>
      </NInput>
    </div>

    <div v-if="unavailable" class="o-card unavailable">
      <Ban :size="18" />
      <span>{{ t('connections.unavailable') }}</span>
    </div>

    <div v-else-if="!loading && !filtered.length" class="o-card">
      <OEmptyState
        :title="t('connections.empty_title')"
        :description="t('connections.empty_desc')"
        :icon="Cable"
      />
    </div>

    <div v-else class="table o-card">
      <div class="head">
        <span>{{ t('connections.user') }}</span>
        <span>{{ t('connections.destination') }}</span>
        <span>{{ t('connections.chain') }}</span>
        <span>{{ t('common.up') }} / {{ t('common.down') }}</span>
        <span>{{ t('connections.duration') }}</span>
        <span />
      </div>
      <div v-for="item in filtered" :key="item.id" class="row">
        <div class="user">
          <span class="avatar">{{
            String(item.metadata?.user || '?')
              .slice(0, 1)
              .toUpperCase()
          }}</span>
          <div>
            <strong>{{ item.metadata?.user || '—' }}</strong>
            <span class="o-micro o-subtle">{{
              item.metadata?.inbound || item.metadata?.type || '—'
            }}</span>
          </div>
        </div>
        <div class="dest">
          <strong class="o-truncate">{{
            item.metadata?.host || item.metadata?.destinationIP || '—'
          }}</strong>
          <span class="o-micro o-subtle">
            {{ item.metadata?.destinationIP }}:{{ item.metadata?.destinationPort }} ·
            {{ item.metadata?.network }}
          </span>
        </div>
        <div class="chain">
          <span v-for="link in item.chains" :key="link" class="chip">{{ link }}</span>
          <span v-if="item.rule" class="o-micro o-subtle">{{ item.rule }}</span>
        </div>
        <div class="traffic o-nums">
          <span>{{ formatBytes(item.upload) }}</span>
          <span class="o-subtle">{{ formatBytes(item.download) }}</span>
        </div>
        <div class="duration o-small o-muted">{{ duration(item) }}</div>
        <div class="actions">
          <NButton size="tiny" quaternary circle @click="closeConnection(item)">
            <template #icon><XCircle :size="15" /></template>
          </NButton>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.summary {
  display: flex;
  gap: 26px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  align-items: center;
}
.summary > div {
  display: flex;
  align-items: center;
  gap: 7px;
}
.summary span {
  color: var(--text-3);
  font-size: 11px;
}
.summary strong {
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.pause {
  margin-left: auto;
}
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.toolbar :deep(.n-input) {
  max-width: 320px;
}
.unavailable {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px;
  color: var(--text-2);
  font-size: 13px;
}
.table {
  overflow: hidden;
}
.head,
.row {
  display: grid;
  grid-template-columns: 150px minmax(180px, 1.4fr) minmax(150px, 1fr) 130px 90px 40px;
  gap: 12px;
  padding: 0 16px;
  align-items: center;
}
.head {
  height: 42px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-3);
  background: color-mix(in srgb, var(--surface-2) 50%, transparent);
  border-bottom: 1px solid var(--border);
}
.row {
  min-height: 62px;
  border-bottom: 1px solid var(--border);
}
.row:last-child {
  border-bottom: 0;
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.avatar {
  width: 28px;
  height: 28px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 9.5px;
  font-weight: 700;
}
.user strong {
  display: block;
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dest {
  min-width: 0;
}
.dest strong {
  display: block;
  font-size: 11.5px;
}
.dest span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chain {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  align-items: center;
  min-width: 0;
}
.chip {
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-3);
}
.traffic {
  display: flex;
  flex-direction: column;
  font-size: 10.5px;
}
.duration {
  font-size: 11px;
}
.actions {
  display: flex;
  justify-content: flex-end;
}
@media (max-width: 900px) {
  .head {
    display: none;
  }
  .row {
    grid-template-columns: 1fr auto;
    padding: 12px;
    gap: 6px;
  }
  .dest {
    grid-column: 1 / -1;
  }
  .chain,
  .duration {
    grid-column: 1;
  }
  .traffic {
    grid-column: 2;
    grid-row: 1;
    text-align: right;
  }
  .actions {
    grid-column: 2;
  }
}
</style>
