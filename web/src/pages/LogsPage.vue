<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, NSelect, NSwitch } from 'naive-ui'
import { Download, Pause, Play, RefreshCw, Search, Terminal, Trash2 } from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { LogRecord } from '@/api/types'
import { useEventStore } from '@/stores/events'

const { t } = useI18n()
const events = useEventStore()

const source = ref<'ostium' | 'core'>('ostium')
const level = ref<string | null>(null)
const search = ref('')
const follow = ref(true)
const paused = ref(false)
const records = ref<LogRecord[]>([])
const lines = ref<string[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const container = ref<HTMLElement | null>(null)
let timer: number | null = null

const levelOptions = computed(() => [
  { label: t('logs.all_levels'), value: '' },
  { label: 'Debug', value: 'debug' },
  { label: 'Info', value: 'info' },
  { label: 'Warning', value: 'warning' },
  { label: 'Error', value: 'error' },
])

const filteredRecords = computed(() => {
  let list = records.value
  if (level.value) list = list.filter((item) => item.level === level.value)
  if (search.value.trim()) {
    const needle = search.value.toLowerCase()
    list = list.filter((item) => item.message.toLowerCase().includes(needle))
  }
  return list
})

const filteredLines = computed(() => {
  let list = lines.value
  if (search.value.trim()) {
    const needle = search.value.toLowerCase()
    list = list.filter((item) => item.toLowerCase().includes(needle))
  }
  return list
})

async function load() {
  loading.value = true
  error.value = null
  try {
    const data = await api.logs.get(source.value, level.value || undefined, undefined, 800)
    records.value = data.records || []
    lines.value = data.lines || []
    if (data.unavailable) error.value = data.error || t('logs.unavailable', { message: '' })
    if (follow.value) await scrollToBottom()
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

function appendRecord(record: LogRecord) {
  if (source.value !== 'ostium' || paused.value) return
  records.value.push(record)
  if (records.value.length > 2000) records.value.shift()
  if (follow.value) void scrollToBottom()
}

watch(
  () => events.lastLog,
  (frame) => {
    if (!frame) return
    const data = frame.data as unknown as LogRecord
    if (data?.message) appendRecord(data)
  },
)

watch(source, () => {
  records.value = []
  lines.value = []
  if (source.value === 'core') {
    startPolling()
  } else if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
  void load()
})

async function scrollToBottom() {
  await nextTick()
  if (container.value) container.value.scrollTop = container.value.scrollHeight
}

function togglePause() {
  paused.value = !paused.value
}

function startPolling() {
  if (timer !== null) clearInterval(timer)
  timer = window.setInterval(() => {
    if (!paused.value && !document.hidden && source.value === 'core') void load()
  }, 2500)
}

function clearView() {
  records.value = []
  lines.value = []
}

onMounted(() => {
  void load()
  startPolling()
})
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer)
})
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('logs.title')" :subtitle="t('logs.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton secondary tag="a" :href="api.logs.downloadUrl(source)" target="_blank">
          <template #icon><Download :size="15" /></template>
          {{ t('logs.download') }}
        </NButton>
      </template>
    </OPageHeader>

    <div class="toolbar">
      <div class="source-tabs">
        <button type="button" :class="{ active: source === 'ostium' }" @click="source = 'ostium'">
          {{ t('logs.source_ostium') }}
        </button>
        <button type="button" :class="{ active: source === 'core' }" @click="source = 'core'">
          {{ t('logs.source_core') }}
        </button>
      </div>
      <NSelect
        v-if="source === 'ostium'"
        v-model:value="level"
        :options="levelOptions"
        size="small"
        class="level"
      />
      <NInput
        v-model:value="search"
        size="small"
        clearable
        :placeholder="t('logs.search')"
        data-search
        class="search"
      >
        <template #prefix><Search :size="14" /></template>
      </NInput>
      <div class="spacer" />
      <label class="follow">
        <span>{{ t('logs.follow') }}</span>
        <NSwitch v-model:value="follow" size="small" :aria-label="t('logs.follow')" />
      </label>
      <NButton size="small" secondary @click="togglePause">
        <template #icon><component :is="paused ? Play : Pause" :size="14" /></template>
        {{ paused ? t('common.resume') : t('logs.pause') }}
      </NButton>
      <NButton size="small" secondary @click="clearView">
        <template #icon><Trash2 :size="14" /></template>
        {{ t('logs.clear') }}
      </NButton>
    </div>

    <div v-if="error" class="log-error">{{ error }}</div>

    <div class="log-card o-card">
      <div class="log-head">
        <Terminal :size="14" />
        <span>{{ source === 'core' ? 'ostium-core' : 'ostium.service' }}</span>
        <span class="o-subtle">{{ paused ? t('common.paused') : t('common.live') }}</span>
      </div>
      <div ref="container" class="log-body o-scroll">
        <template v-if="source === 'ostium'">
          <div
            v-for="(record, index) in filteredRecords"
            :key="`${record.ts}-${index}`"
            class="log-line"
          >
            <span class="ts">{{ record.ts.slice(11, 19) }}</span>
            <span class="level" :class="record.level">{{ record.level.toUpperCase() }}</span>
            <span class="msg">{{ record.message }}</span>
            <span v-if="Object.keys(record.context).length" class="ctx">
              {{
                Object.entries(record.context)
                  .map(([key, value]) => `${key}=${value}`)
                  .join(' ')
              }}
            </span>
          </div>
        </template>
        <template v-else>
          <div v-for="(line, index) in filteredLines" :key="index" class="log-line raw">
            {{ line }}
          </div>
        </template>
        <OEmptyState
          v-if="!filteredRecords.length && !filteredLines.length"
          compact
          :title="t('logs.empty')"
          :description="t('logs.empty')"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.source-tabs {
  display: inline-flex;
  padding: 3px;
  gap: 2px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.source-tabs button {
  border: 0;
  background: transparent;
  color: var(--text-2);
  font-size: 11.5px;
  padding: 5px 12px;
  border-radius: 7px;
  cursor: pointer;
}
.source-tabs button.active {
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow-1);
}
.level {
  width: 130px;
}
.search {
  width: 220px;
}
.spacer {
  flex: 1;
}
.follow {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: var(--text-2);
}
.log-error {
  padding: 10px 12px;
  border-radius: 9px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 11.5px;
  margin-bottom: 10px;
}
.log-card {
  overflow: hidden;
  background: color-mix(in srgb, var(--bg) 72%, #000 10%);
}
.log-head {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text-3);
  font-size: 10.5px;
  font-family: var(--font-mono);
}
.log-head span:nth-child(2) {
  flex: 1;
}
.log-body {
  height: min(62vh, 640px);
  overflow-y: auto;
  padding: 10px 0;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.75;
}
.log-line {
  display: flex;
  gap: 10px;
  padding: 1px 14px;
  white-space: pre-wrap;
  word-break: break-word;
}
.log-line:hover {
  background: color-mix(in srgb, var(--accent) 4%, transparent);
}
.ts {
  color: var(--text-3);
  opacity: 0.7;
  flex: none;
}
.level {
  flex: none;
  width: 58px;
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.level.info {
  color: var(--info);
}
.level.warning,
.level.warn {
  color: var(--warning);
}
.level.error {
  color: var(--danger);
}
.level.debug {
  color: var(--text-3);
}
.msg {
  color: var(--text-2);
}
.ctx {
  color: var(--text-3);
}
.raw {
  color: var(--text-2);
}
@media (max-width: 767px) {
  .search {
    width: 100%;
  }
  .level {
    width: 110px;
  }
  .log-line {
    font-size: 10.5px;
  }
}
</style>
