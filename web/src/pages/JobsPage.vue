<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NModal, NProgress, useMessage } from 'naive-ui'
import { Ban, CheckCircle2, CircleX, LoaderCircle, RefreshCw, XCircle } from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { Job } from '@/api/types'
import { formatDate } from '@/utils/format'

const { t, locale } = useI18n()
const message = useMessage()

const jobs = ref<Job[]>([])
const loading = ref(true)
const selected = ref<Job | null>(null)
const detailOpen = ref(false)
let timer: number | null = null

const activeCount = computed(
  () => jobs.value.filter((job) => job.status === 'running' || job.status === 'queued').length,
)

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    jobs.value = (await api.jobs.list(200)).jobs
  } catch (err) {
    if (!silent) message.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

function icon(status: string) {
  if (status === 'succeeded') return CheckCircle2
  if (status === 'failed') return CircleX
  if (status === 'running' || status === 'queued') return LoaderCircle
  return Ban
}

async function cancel(job: Job) {
  try {
    await api.jobs.cancel(job.id)
    message.success(t('jobs.cancel'))
    await load(true)
  } catch (err) {
    message.error((err as Error).message)
  }
}

function openDetail(job: Job) {
  selected.value = job
  detailOpen.value = true
}

onMounted(() => {
  void load()
  timer = window.setInterval(() => {
    if (!document.hidden) void load(true)
  }, 3000)
})
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer)
})
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('jobs.title')" :subtitle="t('jobs.subtitle')">
      <template #actions>
        <span v-if="activeCount" class="active-pill"
          >{{ activeCount }} {{ t('common.running') }}</span
        >
        <NButton secondary :loading="loading" @click="load()">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
      </template>
    </OPageHeader>

    <div v-if="!loading && !jobs.length" class="o-card">
      <OEmptyState :title="t('jobs.empty')" :description="t('jobs.subtitle')" />
    </div>

    <div v-else class="jobs o-card">
      <div v-for="job in jobs" :key="job.id" class="job" @click="openDetail(job)">
        <div class="job-main">
          <span class="job-icon" :class="job.status">
            <component :is="icon(job.status)" :size="17" :stroke-width="1.8" />
          </span>
          <div class="job-copy">
            <div class="job-title">
              <strong>{{ job.type }}</strong>
              <OStatusPill :status="job.status" size="sm" />
            </div>
            <p class="o-small o-muted">{{ job.message || '—' }}</p>
            <NProgress
              v-if="job.status === 'running' || job.status === 'queued'"
              type="line"
              :percentage="job.progress"
              :show-indicator="false"
              :aria-label="job.type"
              size="small"
            />
          </div>
          <div class="job-side">
            <span class="o-micro o-subtle">{{ formatDate(job.created_at, locale) }}</span>
            <NButton
              v-if="job.status === 'running' || job.status === 'queued'"
              size="tiny"
              secondary
              @click.stop="cancel(job)"
            >
              <template #icon><XCircle :size="13" /></template>
              {{ t('jobs.cancel') }}
            </NButton>
          </div>
        </div>
      </div>
    </div>

    <NModal
      v-model:show="detailOpen"
      preset="card"
      :style="{ width: 'min(620px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('jobs.detail') }}</template>
      <div v-if="selected" class="detail">
        <div class="detail-row">
          <span>{{ t('jobs.type') }}</span><strong>{{ selected.type }}</strong>
        </div>
        <div class="detail-row">
          <span>{{ t('common.status') }}</span><OStatusPill :status="selected.status" size="sm" />
        </div>
        <div class="detail-row">
          <span>{{ t('jobs.progress') }}</span><strong>{{ selected.progress }}%</strong>
        </div>
        <div class="detail-row">
          <span>{{ t('jobs.message') }}</span><strong>{{ selected.message }}</strong>
        </div>
        <div class="detail-row">
          <span>{{ t('jobs.started') }}</span><strong>{{
            formatDate(selected.started_at, locale)
          }}</strong>
        </div>
        <div class="detail-row">
          <span>{{ t('jobs.finished') }}</span><strong>{{
            formatDate(selected.finished_at, locale)
          }}</strong>
        </div>
        <div v-if="selected.error" class="error-block">
          <p>{{ t('jobs.error') }}</p>
          <pre>{{ selected.error }}</pre>
        </div>
        <div v-if="selected.result" class="result-block">
          <p>{{ t('jobs.result') }}</p>
          <pre>{{ JSON.stringify(selected.result, null, 2) }}</pre>
        </div>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.active-pill {
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 10.5px;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
}
.jobs {
  overflow: hidden;
}
.job {
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.job:last-child {
  border-bottom: 0;
}
.job:hover {
  background: color-mix(in srgb, var(--accent) 4%, transparent);
}
.job-main {
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  align-items: flex-start;
}
.job-icon {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--surface-2);
  color: var(--text-3);
}
.job-icon.succeeded {
  color: var(--success);
  background: var(--success-soft);
}
.job-icon.failed {
  color: var(--danger);
  background: var(--danger-soft);
}
.job-icon.running,
.job-icon.queued {
  color: var(--accent);
  background: var(--accent-soft);
}
.job-copy {
  flex: 1;
  min-width: 0;
}
.job-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.job-title strong {
  font-size: 12px;
  font-weight: 600;
}
.job-copy p {
  margin: 3px 0 6px;
}
.job-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}
.detail {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.detail-row span {
  color: var(--text-3);
}
.detail-row strong {
  font-weight: 500;
  text-align: right;
  word-break: break-word;
}
.error-block,
.result-block {
  margin-top: 8px;
}
.error-block p,
.result-block p {
  font-size: 11px;
  color: var(--text-3);
  margin-bottom: 4px;
}
pre {
  margin: 0;
  padding: 10px;
  border-radius: 8px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 10.5px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}
.error-block pre {
  color: var(--danger);
  background: var(--danger-soft);
}
</style>
