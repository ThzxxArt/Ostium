<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NSelect } from 'naive-ui'
import { Activity, ArrowDownToLine, ArrowUpFromLine, BarChart3, RefreshCw } from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OStatCard from '@/components/OStatCard.vue'
import OSectionCard from '@/components/OSectionCard.vue'
import OTrafficChart from '@/components/OLazyChart.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { ConnectionEntry, StatsOverview, TrafficPoint } from '@/api/types'
import { formatBytes } from '@/utils/format'

const { t } = useI18n()

const overview = ref<StatsOverview | null>(null)
const series = ref<TrafficPoint[]>([])
const connections = ref<ConnectionEntry[]>([])
const days = ref(7)
const loading = ref(true)

const totalUp = computed(() => series.value.reduce((sum, point) => sum + point.up, 0))
const totalDown = computed(() => series.value.reduce((sum, point) => sum + point.down, 0))
const topDestinations = computed(() => {
  const map = new Map<string, number>()
  for (const connection of connections.value) {
    const key = String(connection.metadata?.host || connection.metadata?.destinationIP || '—')
    map.set(key, (map.get(key) || 0) + connection.upload + connection.download)
  }
  return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8)
})

async function load() {
  loading.value = true
  try {
    const [stats, traffic, connectionData] = await Promise.all([
      api.stats.overview(),
      api.stats.traffic(days.value),
      api.stats.connections(),
    ])
    overview.value = stats
    series.value = traffic.series
    connections.value = connectionData.connections
  } catch {
    /* handled by empty states */
  } finally {
    loading.value = false
  }
}

async function changeDays(value: number) {
  days.value = value
  const traffic = await api.stats.traffic(days.value)
  series.value = traffic.series
}

onMounted(load)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('stats.title')" :subtitle="t('stats.subtitle')">
      <template #actions>
        <NSelect
          :value="days"
          :options="[
            { label: t('stats.today'), value: 1 },
            { label: t('stats.week'), value: 7 },
            { label: t('stats.month'), value: 30 },
            { label: '90d', value: 90 },
          ]"
          size="small"
          style="width: 120px"
          @update:value="changeDays"
        />
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
      </template>
    </OPageHeader>

    <div class="o-grid o-grid-4">
      <OStatCard
        :label="t('stats.total_down')"
        :value="formatBytes(totalDown)"
        :hint="`${days} ${t('common.days')}`"
        :icon="ArrowDownToLine"
        tone="info"
        :loading="loading"
      />
      <OStatCard
        :label="t('stats.total_up')"
        :value="formatBytes(totalUp)"
        :hint="`${days} ${t('common.days')}`"
        :icon="ArrowUpFromLine"
        tone="accent"
        :loading="loading"
      />
      <OStatCard
        :label="t('home.session')"
        :value="
          formatBytes((overview?.traffic.session_up || 0) + (overview?.traffic.session_down || 0))
        "
        :hint="`${overview?.connections || 0} ${t('nav.connections')}`"
        :icon="Activity"
        tone="success"
        :loading="loading"
      />
      <OStatCard
        :label="t('home.today')"
        :value="
          formatBytes((overview?.traffic.today_up || 0) + (overview?.traffic.today_down || 0))
        "
        :hint="`${formatBytes(overview?.traffic.today_down)} ↓`"
        :icon="BarChart3"
        tone="warning"
        :loading="loading"
      />
    </div>

    <OSectionCard
      :title="days === 1 ? t('stats.today') : `${days} ${t('common.days')}`"
      :icon="BarChart3"
    >
      <OTrafficChart v-if="series.length" :series="series" :height="320" />
      <OEmptyState v-else compact :title="t('stats.no_data')" :description="t('stats.no_data')" />
    </OSectionCard>

    <OSectionCard :title="t('stats.top_destinations')" :icon="Activity">
      <OEmptyState
        v-if="!topDestinations.length"
        compact
        :title="t('connections.empty_title')"
        :description="t('connections.empty_desc')"
      />
      <div v-else class="dest-list">
        <div v-for="[host, bytes] in topDestinations" :key="host" class="dest">
          <strong class="o-truncate">{{ host }}</strong>
          <span class="o-mono">{{ formatBytes(bytes) }}</span>
        </div>
      </div>
    </OSectionCard>
  </div>
</template>

<style scoped>
.dest-list {
  display: flex;
  flex-direction: column;
}
.dest {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 11.5px;
}
.dest:last-child {
  border-bottom: 0;
}
.dest strong {
  flex: 1;
  min-width: 0;
  font-weight: 500;
}
.dest span {
  color: var(--text-2);
}
</style>
