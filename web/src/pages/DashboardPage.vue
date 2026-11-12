<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton, NProgress } from 'naive-ui'
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  Cpu,
  Gauge,
  HardDrive,
  MemoryStick,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  Users,
  Waypoints,
} from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OSectionCard from '@/components/OSectionCard.vue'
import OStatCard from '@/components/OStatCard.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OTrafficChart from '@/components/OLazyChart.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import OErrorState from '@/components/OErrorState.vue'
import { api } from '@/api'
import type {
  Alert,
  Certificate,
  Inbound,
  StatsOverview,
  SystemInfo,
  TrafficPoint,
} from '@/api/types'
import {
  formatBytes,
  formatDuration,
  formatPercent,
  formatRate,
  relativeTime,
} from '@/utils/format'
import { useEventStore } from '@/stores/events'

const { t, locale } = useI18n()
const router = useRouter()
const events = useEventStore()

const overview = ref<StatsOverview | null>(null)
const traffic = ref<TrafficPoint[]>([])
const alerts = ref<Alert[]>([])
const inbounds = ref<Inbound[]>([])
const certificates = ref<Certificate[]>([])
const info = ref<SystemInfo | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref<string | null>(null)
let timer: number | null = null

const activeInbounds = computed(() => inbounds.value.filter((item) => item.enabled).length)
const running = computed(() => overview.value?.engine.running ?? false)
const uptime = computed(() => {
  const start = overview.value?.engine.started_at
  if (!start) return '—'
  return formatDuration((Date.now() - new Date(start).getTime()) / 1000)
})
const recentEvents = computed(() => events.frames.slice(-6).reverse())

async function load(silent = false) {
  if (!silent) loading.value = true
  refreshing.value = true
  try {
    const [stats, series, alertData, inboundData, certData, systemInfo] = await Promise.all([
      api.stats.overview(),
      api.stats.traffic(7),
      api.alerts.list(),
      api.inbounds.list(),
      api.certificates.list(),
      api.system.info(),
    ])
    overview.value = stats
    traffic.value = series.series
    alerts.value = alertData.alerts
    inbounds.value = inboundData.inbounds
    certificates.value = certData.certificates
    info.value = systemInfo
    error.value = null
  } catch (err) {
    if (!silent) error.value = (err as Error).message
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

onMounted(() => {
  void load()
  timer = window.setInterval(() => load(true), 8000)
})
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer)
})

function eventLabel(type: string): string {
  const map: Record<string, string> = {
    'engine.applied': 'Configuration applied',
    'stats.tick': 'Traffic sample',
    'job.created': 'Job queued',
    'job.updated': 'Job updated',
    'alert.created': 'New alert',
    'quota.exceeded': 'Quota enforced',
    'system.proxy': 'System proxy changed',
  }
  return map[type] || type
}
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('dashboard.title')" :subtitle="t('dashboard.subtitle')">
      <template #actions>
        <NButton secondary :loading="refreshing" @click="load()">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton type="primary" @click="router.push('/users?create=1')">
          <template #icon><Plus :size="16" /></template>
          {{ t('dashboard.add_user') }}
        </NButton>
      </template>
    </OPageHeader>

    <OErrorState v-if="error && !overview" :message="error" @retry="load()" />

    <div v-else class="o-stack">
      <section class="pulse-grid">
        <article class="pulse o-card">
          <div class="pulse-copy">
            <div class="pulse-top">
              <span class="o-kicker">{{ t('dashboard.server_pulse') }}</span>
              <OStatusPill
                :status="running ? 'connected' : 'disconnected'"
                :label="running ? t('dashboard.engine_running') : t('dashboard.engine_stopped')"
                :pulse="running"
              />
            </div>
            <h2>{{ running ? t('status.connected') : t('status.degraded') }}</h2>
            <p class="o-muted">{{ overview ? t('dashboard.since', { time: uptime }) : '—' }}</p>

            <div class="rates">
              <div class="rate">
                <span class="rate-label"
                  ><ArrowDownToLine :size="14" /> {{ t('common.down') }}</span
                >
                <strong class="o-nums">{{ formatRate(overview?.rates.down) }}</strong>
              </div>
              <div class="rate">
                <span class="rate-label"><ArrowUpFromLine :size="14" /> {{ t('common.up') }}</span>
                <strong class="o-nums">{{ formatRate(overview?.rates.up) }}</strong>
              </div>
              <div class="rate">
                <span class="rate-label"
                  ><Activity :size="14" /> {{ t('dashboard.today_traffic') }}</span
                >
                <strong class="o-nums">
                  {{
                    formatBytes(
                      (overview?.traffic.today_up || 0) + (overview?.traffic.today_down || 0),
                    )
                  }}
                </strong>
              </div>
            </div>

            <div class="pulse-actions">
              <span class="meta"
                ><Server :size="13" /> {{ overview?.engine.engine_version || '—' }}</span
              >
              <span class="meta"
                ><Gauge :size="13" /> {{ overview?.connections || 0 }}
                {{ t('nav.connections') }}</span
              >
              <span class="meta"
                ><ShieldCheck :size="13" /> {{ activeInbounds }}
                {{ t('dashboard.active_inbounds') }}</span
              >
            </div>
          </div>

          <div class="pulse-visual" aria-hidden="true">
            <div class="halo" :class="{ live: running }">
              <div class="ring r1" />
              <div class="ring r2" />
              <div class="ring r3" />
              <div class="core">
                <Server :size="30" :stroke-width="1.4" />
                <span class="core-dot" />
              </div>
            </div>
          </div>
        </article>

        <div class="health-stack">
          <OSectionCard :title="t('dashboard.health')" :icon="Activity" padding="compact">
            <div class="health-list">
              <div class="health-item">
                <span class="health-label"><Cpu :size="14" /> {{ t('system.cpu') }}</span>
                <span class="health-value o-nums">{{
                  formatPercent(info?.metrics.cpu_percent)
                }}</span>
              </div>
              <NProgress
                type="line"
                :percentage="info?.metrics.cpu_percent || 0"
                :show-indicator="false"
                size="small"
              />
              <div class="health-item">
                <span class="health-label"
                  ><MemoryStick :size="14" /> {{ t('system.memory') }}</span
                >
                <span class="health-value o-nums">{{
                  formatPercent(info?.metrics.memory_percent)
                }}</span>
              </div>
              <NProgress
                type="line"
                :percentage="info?.metrics.memory_percent || 0"
                :show-indicator="false"
                size="small"
              />
              <div class="health-item">
                <span class="health-label"><HardDrive :size="14" /> {{ t('system.disk') }}</span>
                <span class="health-value o-nums">{{
                  formatPercent(info?.metrics.disk_percent)
                }}</span>
              </div>
              <NProgress
                type="line"
                :percentage="info?.metrics.disk_percent || 0"
                :show-indicator="false"
                size="small"
              />
            </div>
          </OSectionCard>

          <OSectionCard :title="t('dashboard.certificates')" :icon="ShieldCheck" padding="compact">
            <div v-if="!certificates.length" class="mini-empty">{{ t('certs.no_certs') }}</div>
            <div v-else class="cert-list">
              <div v-for="cert in certificates.slice(0, 3)" :key="cert.id" class="cert-row">
                <div>
                  <strong>{{ cert.domain }}</strong>
                  <span class="o-micro o-subtle">{{ cert.source }}</span>
                </div>
                <OStatusPill
                  :status="
                    (cert.days_remaining ?? 0) < 0
                      ? 'expired'
                      : (cert.days_remaining ?? 99) < 14
                        ? 'warning'
                        : 'ready'
                  "
                  :label="t('certs.days_left', { days: cert.days_remaining ?? 0 })"
                  size="sm"
                />
              </div>
            </div>
          </OSectionCard>
        </div>
      </section>

      <section class="o-grid o-grid-4">
        <OStatCard
          :label="t('dashboard.today_traffic')"
          :value="
            formatBytes((overview?.traffic.today_up || 0) + (overview?.traffic.today_down || 0))
          "
          :hint="`${formatBytes(overview?.traffic.today_down)} ${t('common.down')} · ${formatBytes(overview?.traffic.today_up)} ${t('common.up')}`"
          :icon="Activity"
          tone="accent"
          :loading="loading"
        />
        <OStatCard
          :label="t('dashboard.live_rate')"
          :value="formatRate((overview?.rates.down || 0) + (overview?.rates.up || 0))"
          :hint="`${formatRate(overview?.rates.down)} ${t('common.down')}`"
          :icon="Gauge"
          tone="info"
          :loading="loading"
        />
        <OStatCard
          :label="t('dashboard.online_users')"
          :value="overview?.users.online || 0"
          :hint="`${overview?.users.enabled || 0} / ${overview?.users.total || 0} ${t('common.enabled')}`"
          :icon="Users"
          tone="success"
          :loading="loading"
        />
        <OStatCard
          :label="t('dashboard.active_inbounds')"
          :value="activeInbounds"
          :hint="`${inbounds.length} ${t('inbounds.title')}`"
          :icon="Waypoints"
          tone="warning"
          :loading="loading"
        />
      </section>

      <section class="chart-grid">
        <OSectionCard :title="t('dashboard.traffic_7d')" :icon="Activity">
          <template #actions>
            <NButton size="tiny" quaternary @click="router.push('/stats')">{{
              t('common.view_all')
            }}</NButton>
          </template>
          <OTrafficChart :series="traffic" :height="280" />
        </OSectionCard>

        <OSectionCard :title="t('dashboard.online_now')" :icon="Users">
          <div v-if="!overview?.online_users.length" class="mini-empty">
            {{ t('dashboard.no_online') }}
          </div>
          <ul v-else class="online-list">
            <li v-for="user in overview.online_users.slice(0, 7)" :key="user.id">
              <span class="avatar">{{ user.name.slice(0, 1).toUpperCase() }}</span>
              <div class="user-copy">
                <strong>{{ user.name }}</strong>
                <span class="o-micro o-subtle">{{ formatBytes(user.up + user.down) }}</span>
              </div>
              <span class="online-dot" />
            </li>
          </ul>
        </OSectionCard>
      </section>

      <section class="bottom-grid">
        <OSectionCard :title="t('dashboard.alerts')" :icon="ShieldCheck">
          <OEmptyState
            v-if="!alerts.length"
            compact
            :title="t('dashboard.no_alerts')"
            :description="t('dashboard.no_alerts')"
          />
          <ul v-else class="alert-list">
            <li v-for="alert in alerts.slice(0, 4)" :key="alert.id" class="alert-row">
              <span class="alert-dot" :class="alert.level" />
              <div class="alert-copy">
                <p>{{ alert.message }}</p>
                <span class="o-micro o-subtle">{{ relativeTime(alert.created_at, locale) }}</span>
              </div>
            </li>
          </ul>
        </OSectionCard>

        <OSectionCard :title="t('dashboard.quick_actions')" :icon="Gauge">
          <div class="quick-grid">
            <button type="button" @click="router.push('/users?create=1')">
              <Users :size="18" /><span>{{ t('users.add') }}</span>
            </button>
            <button type="button" @click="router.push('/subscriptions')">
              <ShieldCheck :size="18" /><span>{{ t('dashboard.view_subscriptions') }}</span>
            </button>
            <button type="button" @click="router.push('/logs')">
              <Activity :size="18" /><span>{{ t('dashboard.open_logs') }}</span>
            </button>
            <button type="button" @click="router.push('/system')">
              <Server :size="18" /><span>{{ t('dashboard.run_doctor') }}</span>
            </button>
          </div>
          <div class="recent">
            <p class="o-micro o-subtle">{{ t('dashboard.recent_events') }}</p>
            <ul v-if="recentEvents.length">
              <li v-for="event in recentEvents" :key="`${event.type}-${event.ts}`">
                <span class="event-type">{{ eventLabel(event.type) }}</span>
                <span class="o-micro o-subtle">{{ relativeTime(event.ts, locale) }}</span>
              </li>
            </ul>
            <p v-else class="mini-empty">{{ t('dashboard.no_events') }}</p>
          </div>
        </OSectionCard>
      </section>
    </div>
  </div>
</template>

<style scoped>
.pulse-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(300px, 0.85fr);
  gap: 20px;
}
.pulse {
  position: relative;
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 16px;
  padding: 26px 28px;
  overflow: hidden;
  background:
    radial-gradient(560px 300px at 82% 40%, rgba(45, 212, 191, 0.12), transparent 65%),
    var(--surface);
}
.pulse-copy {
  position: relative;
  z-index: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.pulse-top {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
h2 {
  font-size: 30px;
  letter-spacing: -0.04em;
  font-weight: 600;
  margin-top: 14px;
}
.rates {
  display: flex;
  gap: 30px;
  margin-top: 22px;
  flex-wrap: wrap;
}
.rate {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.rate-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.rate strong {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
}
.pulse-actions {
  margin-top: auto;
  padding-top: 22px;
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.meta {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-3);
  font-size: 10.5px;
}
.pulse-visual {
  width: 220px;
  flex: none;
  display: grid;
  place-items: center;
  position: relative;
}
.halo {
  position: relative;
  width: 190px;
  height: 190px;
  display: grid;
  place-items: center;
}
.ring {
  position: absolute;
  border-radius: 50%;
  border: 1px solid color-mix(in srgb, var(--accent) 24%, transparent);
}
.r1 {
  inset: 0;
}
.r2 {
  inset: 22px;
  border-style: dashed;
}
.r3 {
  inset: 46px;
  opacity: 0.6;
}
.halo.live .r1 {
  animation: spin 26s linear infinite;
}
.halo.live .r2 {
  animation: spin 18s linear infinite reverse;
}
.halo.live .r3 {
  box-shadow: 0 0 60px color-mix(in srgb, var(--accent) 20%, transparent);
}
.core {
  position: relative;
  width: 86px;
  height: 86px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: var(--accent);
  background: radial-gradient(circle at 35% 28%, rgba(94, 234, 212, 0.24), var(--surface-2) 62%);
  border: 1px solid color-mix(in srgb, var(--accent) 34%, transparent);
  box-shadow:
    inset 0 0 26px rgba(94, 234, 212, 0.14),
    0 0 60px rgba(94, 234, 212, 0.12);
}
.core-dot {
  position: absolute;
  right: 16px;
  top: 16px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 10px var(--success);
}
.health-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.health-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.health-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 4px;
  font-size: 11.5px;
}
.health-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-2);
}
.health-value {
  color: var(--text);
  font-weight: 600;
}
.cert-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.cert-row strong {
  display: block;
  font-size: 11.5px;
  font-weight: 600;
}
.mini-empty {
  color: var(--text-3);
  font-size: 11.5px;
  padding: 8px 0;
}
.chart-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(280px, 0.8fr);
  gap: 20px;
}
.online-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.online-list li {
  display: flex;
  align-items: center;
  gap: 10px;
}
.avatar {
  width: 30px;
  height: 30px;
  flex: none;
  border-radius: 9px;
  display: grid;
  place-items: center;
  color: var(--accent);
  background: var(--accent-soft);
  font-size: 10.5px;
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
.online-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
}
.bottom-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr);
  gap: 20px;
}
.alert-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.alert-row {
  display: flex;
  gap: 9px;
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
.alert-copy p {
  font-size: 12px;
  line-height: 1.45;
}
.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.quick-grid button {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 11px 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
  font-size: 11.5px;
  text-align: left;
}
.quick-grid button:hover {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
}
.recent {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.recent ul {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.recent li {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 11px;
}
.event-type {
  color: var(--text-2);
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 1200px) {
  .pulse-grid,
  .chart-grid,
  .bottom-grid {
    grid-template-columns: 1fr;
  }
  .pulse-visual {
    display: none;
  }
}
@media (max-width: 767px) {
  .pulse {
    padding: 20px;
  }
  .rates {
    gap: 18px;
  }
  h2 {
    font-size: 24px;
  }
}
</style>
