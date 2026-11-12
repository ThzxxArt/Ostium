<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, useMessage } from 'naive-ui'
import {
  Activity,
  Cpu,
  Download,
  HardDrive,
  MemoryStick,
  RefreshCw,
  Server,
  ShieldCheck,
  Stethoscope,
  Terminal,
} from 'lucide-vue-next'
import OPageHeader from '@/components/OPageHeader.vue'
import OSectionCard from '@/components/OSectionCard.vue'
import OStatCard from '@/components/OStatCard.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { DoctorCheck, ServiceStatus, SystemInfo } from '@/api/types'
import { formatBytes, formatDuration, formatPercent } from '@/utils/format'

const { t } = useI18n()
const message = useMessage()

const info = ref<SystemInfo | null>(null)
const services = ref<ServiceStatus[]>([])
const checks = ref<DoctorCheck[]>([])
const loading = ref(true)
const runningDoctor = ref(false)
const reloading = ref(false)
const error = ref<string | null>(null)

const coreService = computed(() =>
  services.value.find((service) => service.name === 'ostium-core.service'),
)
const controlService = computed(() =>
  services.value.find((service) => service.name === 'ostium.service'),
)
const passCount = computed(() => checks.value.filter((check) => check.status === 'pass').length)
const issueCount = computed(() => checks.value.filter((check) => check.status !== 'pass').length)

async function load() {
  loading.value = true
  try {
    const [infoData, serviceData] = await Promise.all([api.system.info(), api.system.services()])
    info.value = infoData
    services.value = serviceData.services
    error.value = null
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

async function runDoctor() {
  runningDoctor.value = true
  try {
    checks.value = (await api.system.doctor()).checks
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    runningDoctor.value = false
  }
}

async function reloadCore() {
  reloading.value = true
  try {
    await api.system.restart('ostium-core')
    message.success(t('system.reload_done'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    reloading.value = false
  }
}

onMounted(async () => {
  await load()
  await runDoctor()
})
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('system.title')" :subtitle="t('system.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton secondary :loading="reloading" @click="reloadCore">
          <template #icon><Terminal :size="15" /></template>
          {{ t('system.reload') }}
        </NButton>
        <NButton type="primary" tag="a" :href="api.system.diagnosticsUrl()" target="_blank">
          <template #icon><Download :size="16" /></template>
          {{ t('system.download_diagnostics') }}
        </NButton>
      </template>
    </OPageHeader>

    <div class="o-grid o-grid-4">
      <OStatCard
        :label="t('system.cpu')"
        :value="formatPercent(info?.metrics.cpu_percent)"
        :hint="info?.host.machine"
        :icon="Cpu"
        tone="accent"
        :loading="loading"
      />
      <OStatCard
        :label="t('system.memory')"
        :value="formatPercent(info?.metrics.memory_percent)"
        :hint="`${formatBytes(info?.metrics.memory_used)} / ${formatBytes(info?.metrics.memory_total)}`"
        :icon="MemoryStick"
        tone="info"
        :loading="loading"
      />
      <OStatCard
        :label="t('system.disk')"
        :value="formatPercent(info?.metrics.disk_percent)"
        :hint="`${formatBytes(info?.metrics.disk_used)} / ${formatBytes(info?.metrics.disk_total)}`"
        :icon="HardDrive"
        tone="warning"
        :loading="loading"
      />
      <OStatCard
        :label="t('common.uptime')"
        :value="formatDuration(info?.control_plane_uptime)"
        :hint="`Ostium ${info?.app.version || ''}`"
        :icon="Activity"
        tone="success"
        :loading="loading"
      />
    </div>

    <div class="split">
      <OSectionCard :title="t('system.services')" :icon="Server">
        <div class="service-list">
          <div class="service">
            <div class="service-copy">
              <strong>{{ t('system.control_plane') }}</strong>
              <span class="o-micro o-subtle">ostium.service · pid {{ info?.host.pid }}</span>
            </div>
            <OStatusPill :status="controlService?.running ? 'running' : 'stopped'" size="sm" />
          </div>
          <div class="service">
            <div class="service-copy">
              <strong>{{ t('system.core') }}</strong>
              <span class="o-micro o-subtle"
                >ostium-core.service · {{ info?.core.engine_version || '—' }}</span
              >
            </div>
            <OStatusPill :status="coreService?.running ? 'running' : 'stopped'" size="sm" />
          </div>
        </div>
        <div class="host-grid">
          <div>
            <span>{{ t('system.host') }}</span><strong>{{ info?.host.hostname }}</strong>
          </div>
          <div>
            <span>{{ t('system.platform') }}</span><strong>{{ info?.host.platform }}</strong>
          </div>
          <div>
            <span>{{ t('system.python') }}</span><strong>{{ info?.host.python }}</strong>
          </div>
          <div>
            <span>{{ t('system.core_version') }}</span><strong>{{
              info?.core.engine_version || '—'
            }}</strong>
          </div>
          <div>
            <span>{{ t('system.config_revision') }}</span><strong class="o-mono">{{
              info?.core.revision || '—'
            }}</strong>
          </div>
          <div>
            <span>{{ t('common.role') }}</span><strong>{{ info?.app.role }}</strong>
          </div>
        </div>
      </OSectionCard>

      <OSectionCard :title="t('system.doctor')" :icon="Stethoscope">
        <template #actions>
          <NButton size="tiny" secondary :loading="runningDoctor" @click="runDoctor">{{
            t('system.run_doctor')
          }}</NButton>
        </template>
        <OEmptyState
          v-if="!checks.length && !runningDoctor"
          compact
          :title="t('system.no_checks')"
          :description="t('system.no_checks')"
        />
        <div v-else class="checks">
          <div class="check-summary">
            <span>{{ t('system.check_pass') }} {{ passCount }}</span>
            <span :class="{ warn: issueCount > 0 }"
              >{{ t('system.check_fail') }} {{ issueCount }}</span
            >
          </div>
          <div v-for="check in checks" :key="check.id" class="check">
            <span class="check-dot" :class="check.status" />
            <div class="check-copy">
              <strong>{{ check.id }}</strong>
              <span>{{ check.message }}</span>
              <small v-if="check.fix">{{ t('diagnostics.fix') }}: {{ check.fix }}</small>
            </div>
            <OStatusPill :status="check.status" size="sm" />
          </div>
        </div>
      </OSectionCard>
    </div>

    <OSectionCard :title="t('system.diagnostics')" :icon="ShieldCheck">
      <p class="o-muted o-small">{{ t('system.diagnostics_hint') }}</p>
      <div class="diag-actions">
        <NButton type="primary" tag="a" :href="api.system.diagnosticsUrl()" target="_blank">
          <template #icon><Download :size="15" /></template>
          {{ t('system.download_diagnostics') }}
        </NButton>
      </div>
    </OSectionCard>
  </div>
</template>

<style scoped>
.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr);
  gap: 20px;
}
.service-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.service {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 12px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.service-copy strong {
  display: block;
  font-size: 12px;
}
.host-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
}
.host-grid div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.host-grid span {
  color: var(--text-3);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.host-grid strong {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-2);
  word-break: break-word;
}
.checks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.check-summary {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--success);
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.check-summary .warn {
  color: var(--warning);
}
.check {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}
.check-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 5px;
  flex: none;
  background: var(--success);
}
.check-dot.warn {
  background: var(--warning);
}
.check-dot.fail {
  background: var(--danger);
}
.check-copy {
  flex: 1;
  min-width: 0;
}
.check-copy strong {
  display: block;
  font-size: 11px;
  font-weight: 600;
}
.check-copy span {
  display: block;
  color: var(--text-2);
  font-size: 10.5px;
  line-height: 1.45;
}
.check-copy small {
  display: block;
  color: var(--text-3);
  font-size: 10px;
  margin-top: 2px;
}
@media (max-width: 1000px) {
  .split {
    grid-template-columns: 1fr;
  }
}
</style>
