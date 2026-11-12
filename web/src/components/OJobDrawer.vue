<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NDrawer, NDrawerContent, NProgress, NSpin, NButton } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { Ban, CheckCircle2, CircleX, ListChecks, LoaderCircle } from '@lucide/vue'
import { api } from '@/api'
import type { Job } from '@/api/types'
import OStatusPill from './OStatusPill.vue'
import { formatDate } from '@/utils/format'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()
const { t, locale } = useI18n()

const visible = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const jobs = ref<Job[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
let timer: number | null = null

async function load() {
  loading.value = true
  try {
    jobs.value = (await api.jobs.list(30)).jobs
    error.value = null
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

async function cancel(job: Job) {
  try {
    await api.jobs.cancel(job.id)
    await load()
  } catch (err) {
    error.value = (err as Error).message
  }
}

watch(
  () => props.show,
  (open) => {
    if (open) {
      void load()
      timer = window.setInterval(load, 3000)
    } else if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  },
)

onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer)
})

function icon(status: string) {
  if (status === 'succeeded') return CheckCircle2
  if (status === 'failed') return CircleX
  if (status === 'running' || status === 'queued') return LoaderCircle
  return Ban
}
</script>

<template>
  <NDrawer v-model:show="visible" :width="420" placement="right">
    <NDrawerContent :title="t('jobs.title')" closable>
      <div class="drawer-body">
        <div class="head">
          <p class="o-muted o-small">{{ t('jobs.subtitle') }}</p>
          <NButton size="tiny" secondary @click="load">{{ t('common.refresh') }}</NButton>
        </div>
        <div v-if="loading && !jobs.length" class="loading"><NSpin size="small" /></div>
        <div v-else-if="error" class="error">{{ error }}</div>
        <div v-else-if="!jobs.length" class="empty">
          <ListChecks :size="26" :stroke-width="1.4" />
          <p>{{ t('jobs.empty') }}</p>
        </div>
        <ul v-else class="jobs">
          <li v-for="job in jobs" :key="job.id" class="job">
            <div class="job-top">
              <span class="job-type">
                <component :is="icon(job.status)" :size="15" :stroke-width="1.8" />
                {{ job.type }}
              </span>
              <OStatusPill :status="job.status" size="sm" />
            </div>
            <p class="job-message">{{ job.message || '—' }}</p>
            <NProgress
              v-if="job.status === 'running' || job.status === 'queued'"
              type="line"
              :percentage="job.progress"
              :show-indicator="false"
              size="small"
            />
            <div class="job-meta">
              <span>{{ formatDate(job.created_at, locale) }}</span>
              <button
                v-if="job.status === 'running' || job.status === 'queued'"
                type="button"
                class="cancel"
                @click="cancel(job)"
              >
                {{ t('jobs.cancel') }}
              </button>
            </div>
            <pre v-if="job.error" class="job-error">{{ job.error }}</pre>
          </li>
        </ul>
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.loading,
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 32px 0;
  color: var(--text-3);
}
.error {
  color: var(--danger);
  font-size: 12.5px;
}
.jobs {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.job {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-2);
}
.job-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.job-type {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  font-weight: 600;
}
.job-message {
  margin: 6px 0 8px;
  color: var(--text-2);
  font-size: 12px;
}
.job-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  color: var(--text-3);
  font-size: 10.5px;
}
.cancel {
  border: 0;
  background: transparent;
  color: var(--danger);
  font-size: 11px;
  cursor: pointer;
}
.job-error {
  margin: 8px 0 0;
  padding: 8px;
  border-radius: 8px;
  background: var(--danger-soft);
  color: var(--danger);
  font-family: var(--font-mono);
  font-size: 10.5px;
  white-space: pre-wrap;
}
</style>
