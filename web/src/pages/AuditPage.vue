<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput } from 'naive-ui'
import { FileClock, RefreshCw, Search } from 'lucide-vue-next'
import OPageHeader from '@/components/OPageHeader.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import OErrorState from '@/components/OErrorState.vue'
import { api } from '@/api'
import type { AuditEntry } from '@/api/types'
import { formatDate } from '@/utils/format'

const { t, locale } = useI18n()
const entries = ref<AuditEntry[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const search = ref('')

const filtered = computed(() => {
  if (!search.value.trim()) return entries.value
  const needle = search.value.toLowerCase()
  return entries.value.filter((entry) =>
    [entry.actor, entry.action, entry.target, entry.ip]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(needle)),
  )
})

async function load() {
  loading.value = true
  try {
    entries.value = (await api.audit.list(300)).entries
    error.value = null
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('audit.title')" :subtitle="t('audit.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
      </template>
    </OPageHeader>

    <div class="toolbar">
      <NInput v-model:value="search" clearable :placeholder="t('common.search')" data-search>
        <template #prefix><Search :size="15" /></template>
      </NInput>
      <span class="o-micro o-subtle">{{ filtered.length }} / {{ entries.length }}</span>
    </div>

    <OErrorState v-if="error" :message="error" @retry="load" />
    <div v-else-if="!loading && !filtered.length" class="o-card">
      <OEmptyState :title="t('audit.empty')" :description="t('audit.empty')" :icon="FileClock" />
    </div>
    <div v-else class="audit o-card">
      <div v-for="entry in filtered" :key="entry.id" class="entry">
        <div class="line">
          <span class="dot" />
          <div class="copy">
            <div class="title">
              <strong>{{ entry.action }}</strong>
              <span v-if="entry.target" class="target">{{ entry.target }}</span>
            </div>
            <div class="meta">
              <span>{{ entry.actor }}</span>
              <span v-if="entry.ip">· {{ entry.ip }}</span>
              <span>· {{ formatDate(entry.created_at, locale) }}</span>
            </div>
          </div>
          <span class="time o-micro o-subtle">{{ entry.created_at.slice(11, 19) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.toolbar :deep(.n-input) {
  max-width: 340px;
}
.audit {
  padding: 8px 20px;
}
.entry {
  position: relative;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}
.entry:last-child {
  border-bottom: 0;
}
.line {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  margin-top: 5px;
  flex: none;
  box-shadow: 0 0 0 4px var(--accent-soft);
}
.copy {
  flex: 1;
  min-width: 0;
}
.title {
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
}
.title strong {
  font-size: 12.5px;
  font-weight: 600;
}
.target {
  font-size: 11px;
  color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 1px 6px;
}
.meta {
  margin-top: 3px;
  color: var(--text-3);
  font-size: 10.5px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.time {
  flex: none;
}
</style>
