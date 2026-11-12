<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton, NSelect, useMessage } from 'naive-ui'
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpFromLine,
  Gauge,
  Link2,
  RefreshCw,
  Stethoscope,
  Waypoints,
  Wifi,
} from 'lucide-vue-next'
import OPageHeader from '@/components/OPageHeader.vue'
import OConnectOrb from '@/components/OConnectOrb.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { ConnectionEntry, Profile, SystemInfo } from '@/api/types'
import { formatBytes, formatDuration, formatRate } from '@/utils/format'

const { t } = useI18n()
const router = useRouter()
const message = useMessage()

const info = ref<SystemInfo | null>(null)
const profiles = ref<Profile[]>([])
const selectedProfileId = ref<string | null>(null)
const connections = ref<ConnectionEntry[]>([])
const loading = ref(true)
const busy = ref(false)
const sessionUp = ref(0)
const sessionDown = ref(0)
const rateUp = ref(0)
const rateDown = ref(0)
const connectedAt = ref<number | null>(null)
let timer: number | null = null
let lastTotals = { up: 0, down: 0, at: Date.now() }

const activeProfile = computed(
  () =>
    profiles.value.find((profile) => profile.id === selectedProfileId.value) ||
    profiles.value[0] ||
    null,
)
const endpoints = computed(() => activeProfile.value?.endpoints || [])
const selectedEndpoint = computed(
  () => activeProfile.value?.selected_endpoint || endpoints.value[0]?.tag || null,
)
const connected = computed(() => Boolean((info.value?.core as Record<string, unknown>)?.running))
const state = computed(() => (connected.value ? 'connected' : 'disconnected'))
const mode = computed(() => info.value?.mode || 'mixed')

const endpointOptions = computed(() =>
  endpoints.value.map((endpoint) => ({
    label: `${endpoint.name || endpoint.tag} · ${endpoint.server}:${endpoint.port}`,
    value: endpoint.tag,
  })),
)

const profileOptions = computed(() =>
  profiles.value.map((profile) => ({ label: profile.name, value: profile.id })),
)

const modeLabel = computed(() => {
  if (mode.value === 'tun') return t('home.mode_tun')
  if (mode.value === 'system_proxy') return t('home.mode_system')
  return t('home.mode_mixed')
})

const warning = computed(() => {
  if (mode.value === 'tun') return t('home.tun_warning')
  if (mode.value === 'system_proxy') return t('home.system_warning')
  return t('home.mixed_warning')
})

async function load() {
  loading.value = true
  try {
    const [systemInfo, profileData, connectionData] = await Promise.all([
      api.system.info(),
      api.profiles.list(),
      api.stats.connections(),
    ])
    info.value = systemInfo
    profiles.value = profileData.profiles
    if (!selectedProfileId.value) {
      const active = profiles.value.find((profile) => profile.endpoints.length)
      selectedProfileId.value = active?.id || profiles.value[0]?.id || null
    }
    connections.value = connectionData.connections
    const up = connectionData.upload_total
    const down = connectionData.download_total
    const now = Date.now()
    const elapsed = Math.max(1, (now - lastTotals.at) / 1000)
    rateUp.value = Math.max(0, (up - lastTotals.up) / elapsed)
    rateDown.value = Math.max(0, (down - lastTotals.down) / elapsed)
    lastTotals = { up, down, at: now }
    sessionUp.value = up
    sessionDown.value = down
    if (connected.value && connectedAt.value === null) connectedAt.value = Date.now()
    if (!connected.value) connectedAt.value = null
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function toggleConnection() {
  if (busy.value) return
  busy.value = true
  try {
    if (connected.value) {
      await api.system.disconnect()
      message.success(t('home.disconnected'))
    } else {
      await api.system.connect()
      message.success(t('home.connected'))
    }
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = false
  }
}

async function selectProfile(id: string) {
  selectedProfileId.value = id
  const profile = profiles.value.find((item) => item.id === id)
  if (profile) {
    await selectEndpoint(profile.selected_endpoint || profile.endpoints[0]?.tag || '')
  }
}

async function selectEndpoint(tag: string) {
  const profile = activeProfile.value
  if (!profile || !tag) return
  try {
    await api.profiles.update(profile.id, { selected_endpoint: tag })
    profile.selected_endpoint = tag
    if (connected.value) await api.system.connect()
    message.success(t('profiles.selected'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  }
}

function connectionDuration(): string {
  if (!connectedAt.value) return '—'
  return formatDuration((Date.now() - connectedAt.value) / 1000)
}

onMounted(async () => {
  await load()
  timer = window.setInterval(load, 4000)
})
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer)
})
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('home.title')" :subtitle="t('home.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton secondary @click="router.push('/diagnostics')">
          <template #icon><Stethoscope :size="15" /></template>
          {{ t('diagnostics.run') }}
        </NButton>
      </template>
    </OPageHeader>

    <div v-if="!loading && !profiles.length" class="o-card">
      <OEmptyState
        :title="t('home.no_profile')"
        :description="t('home.no_profile_desc')"
        :icon="Link2"
      >
        <NButton type="primary" @click="router.push('/profiles')">{{
          t('home.import_now')
        }}</NButton>
        <NButton secondary @click="router.push('/onboarding')">{{ t('onboarding.title') }}</NButton>
      </OEmptyState>
    </div>

    <div v-else class="home-grid">
      <section class="hero o-card">
        <div class="hero-top">
          <div class="mode-chips">
            <span class="chip">{{ modeLabel }}</span>
            <span class="chip subtle"><Wifi :size="12" /> {{ info?.host.hostname }}</span>
          </div>
          <OStatusPill
            :status="connected ? 'connected' : 'disconnected'"
            :label="connected ? t('home.connected') : t('home.disconnected')"
            :pulse="connected"
          />
        </div>

        <OConnectOrb
          :state="state"
          :label="connected ? t('home.disconnect') : t('home.connect')"
          :sublabel="connected ? connectionDuration() : t('home.select_endpoint')"
          :disabled="busy || !profiles.length"
          :size="240"
          @toggle="toggleConnection"
        />

        <div class="rates">
          <div class="rate">
            <span class="rate-icon down"><ArrowDownToLine :size="15" /></span>
            <div>
              <span>{{ t('common.down') }}</span><strong class="o-nums">{{
                formatRate(rateDown)
              }}</strong>
            </div>
          </div>
          <div class="rate">
            <span class="rate-icon up"><ArrowUpFromLine :size="15" /></span>
            <div>
              <span>{{ t('common.up') }}</span><strong class="o-nums">{{
                formatRate(rateUp)
              }}</strong>
            </div>
          </div>
          <div class="rate">
            <span class="rate-icon total"><Gauge :size="15" /></span>
            <div>
              <span>{{ t('home.session') }}</span><strong class="o-nums">{{
                formatBytes(sessionUp + sessionDown)
              }}</strong>
            </div>
          </div>
        </div>
      </section>

      <aside class="side">
        <section class="panel o-card">
          <div class="panel-head">
            <span class="o-kicker">{{ t('home.select_profile') }}</span>
            <NButton text type="primary" size="tiny" @click="router.push('/profiles')">{{
              t('common.details')
            }}</NButton>
          </div>
          <NSelect
            :value="selectedProfileId"
            :options="profileOptions"
            @update:value="selectProfile"
          />
          <div class="endpoint-row">
            <span>{{ t('home.select_endpoint') }}</span>
            <NSelect
              :value="selectedEndpoint"
              :options="endpointOptions"
              size="small"
              @update:value="selectEndpoint"
            />
          </div>
          <div class="active-endpoint">
            <Waypoints :size="16" />
            <div>
              <strong>{{
                endpoints.find((endpoint) => endpoint.tag === selectedEndpoint)?.name ||
                t('common.none')
              }}</strong>
              <span class="o-micro o-subtle">{{
                endpoints.find((endpoint) => endpoint.tag === selectedEndpoint)?.protocol
              }}</span>
            </div>
          </div>
        </section>

        <section class="panel o-card">
          <div class="panel-head">
            <span class="o-kicker">{{ t('common.details') }}</span>
          </div>
          <div class="detail-list">
            <div>
              <span>{{ t('home.mode') }}</span><strong>{{ modeLabel }}</strong>
            </div>
            <div>
              <span>{{ t('common.port') }}</span><strong class="o-mono">{{
                mode === 'tun' ? 'TUN' : '7890'
              }}</strong>
            </div>
            <div>
              <span>{{ t('home.latency') }}</span><strong>—</strong>
            </div>
            <div>
              <span>{{ t('common.version') }}</span><strong>{{ info?.app.version }}</strong>
            </div>
          </div>
          <p class="warning">{{ warning }}</p>
        </section>

        <section class="panel o-card quick">
          <button type="button" @click="router.push('/network')">
            <Wifi :size="17" /><span>{{ t('home.quick_network') }}</span
            ><ArrowRight :size="14" />
          </button>
          <button type="button" @click="router.push('/logs')">
            <Gauge :size="17" /><span>{{ t('home.quick_logs') }}</span
            ><ArrowRight :size="14" />
          </button>
          <button type="button" @click="router.push('/profiles')">
            <Link2 :size="17" /><span>{{ t('nav.profiles') }}</span
            ><ArrowRight :size="14" />
          </button>
        </section>
      </aside>
    </div>

    <section v-if="connections.length" class="recent o-card">
      <header>
        <span class="o-kicker">{{ t('nav.connections') }}</span><span class="o-micro o-subtle">{{
          connections.length
        }}</span>
      </header>
      <div class="recent-list">
        <div v-for="item in connections.slice(0, 6)" :key="item.id" class="recent-row">
          <span class="recent-dot" />
          <strong class="o-truncate">{{
            item.metadata?.host || item.metadata?.destinationIP || '—'
          }}</strong>
          <span class="o-micro o-subtle">{{ item.chains.join(' → ') }}</span>
          <span class="o-micro o-subtle">{{ formatBytes(item.upload + item.download) }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.75fr);
  gap: 20px;
  align-items: stretch;
}
.hero {
  padding: 22px 26px 26px;
  display: flex;
  flex-direction: column;
  align-items: center;
  background:
    radial-gradient(620px 420px at 50% 22%, rgba(45, 212, 191, 0.1), transparent 66%),
    var(--surface);
}
.hero-top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.mode-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, var(--accent) 24%, transparent);
  color: var(--accent);
  background: var(--accent-soft);
}
.chip.subtle {
  color: var(--text-3);
  border-color: var(--border);
  background: var(--surface-2);
}
.hero :deep(.orb-wrap) {
  margin: 26px 0 22px;
}
.rates {
  display: flex;
  gap: 26px;
  flex-wrap: wrap;
  justify-content: center;
  width: 100%;
  padding-top: 18px;
  border-top: 1px solid var(--border);
}
.rate {
  display: flex;
  align-items: center;
  gap: 9px;
}
.rate-icon {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--surface-2);
  color: var(--text-2);
}
.rate-icon.down {
  color: var(--info);
}
.rate-icon.up {
  color: var(--accent);
}
.rate div {
  display: flex;
  flex-direction: column;
}
.rate span {
  font-size: 10px;
  color: var(--text-3);
}
.rate strong {
  font-size: 14px;
  font-weight: 600;
}
.side {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.panel {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.endpoint-row {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.endpoint-row > span {
  font-size: 10px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.active-endpoint {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--accent);
}
.active-endpoint strong {
  display: block;
  font-size: 11.5px;
  color: var(--text);
}
.detail-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.detail-list div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.detail-list span {
  color: var(--text-3);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.detail-list strong {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-2);
}
.warning {
  font-size: 10px;
  line-height: 1.55;
  color: var(--text-3);
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.quick {
  padding: 8px;
  gap: 2px;
}
.quick button {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  font-size: 11.5px;
  cursor: pointer;
  text-align: left;
}
.quick button:hover {
  background: var(--surface-2);
  color: var(--accent);
}
.quick button span {
  flex: 1;
}
.recent {
  margin-top: 20px;
  padding: 16px 18px;
}
.recent header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.recent-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.recent-row {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 11px;
}
.recent-row strong {
  flex: 1;
  min-width: 0;
  font-weight: 500;
}
.recent-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--success);
  flex: none;
}
@media (max-width: 1000px) {
  .home-grid {
    grid-template-columns: 1fr;
  }
}
</style>
