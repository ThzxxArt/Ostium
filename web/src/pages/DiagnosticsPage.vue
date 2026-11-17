<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton } from 'naive-ui'
import {
  CheckCircle2,
  CircleAlert,
  CircleX,
  Copy,
  Download,
  Play,
  Stethoscope,
  Wifi,
} from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { DoctorCheck, SelfTestResult } from '@/api/types'

const { t } = useI18n()
const router = useRouter()

const checks = ref<DoctorCheck[]>([])
const running = ref(false)
const ran = ref(false)
const error = ref('')
const selftesting = ref(false)
const selftest = ref<SelfTestResult | null>(null)

const issues = computed(() => checks.value.filter((check) => check.status !== 'pass').length)
const warnCount = computed(() => checks.value.filter((check) => check.status === 'warn').length)
const failCount = computed(() => checks.value.filter((check) => check.status === 'fail').length)

const groups = computed(() => {
  const definitions = [
    {
      id: 'version',
      label: t('diagnostics.group_version'),
      match: (id: string) => id.startsWith('version'),
    },
    {
      id: 'ports',
      label: t('diagnostics.group_ports'),
      match: (id: string) => id.startsWith('port_owner'),
    },
    {
      id: 'core',
      label: t('diagnostics.group_core'),
      match: (id: string) =>
        id.startsWith('core') ||
        id.startsWith('engine') ||
        id === 'config_drift' ||
        id === 'database',
    },
    { id: 'dns', label: t('diagnostics.group_dns'), match: (id: string) => id.startsWith('dns') },
    {
      id: 'proxy',
      label: t('diagnostics.group_proxy'),
      match: (id: string) =>
        id.startsWith('egress') || id.startsWith('system_proxy') || id.startsWith('tun'),
    },
  ]
  const assigned = new Set<string>()
  const result = definitions.map((definition) => {
    const matched = checks.value.filter((check) => definition.match(check.id))
    for (const check of matched) assigned.add(check.id)
    return { ...definition, checks: matched }
  })
  const rest = checks.value.filter((check) => !assigned.has(check.id))
  if (rest.length)
    result.push({
      id: 'system',
      label: t('diagnostics.group_system'),
      match: () => true,
      checks: rest,
    })
  return result.filter((group) => group.checks.length > 0)
})

async function run() {
  running.value = true
  try {
    checks.value = (await api.system.doctor()).checks
    ran.value = true
    error.value = ''
  } catch (err) {
    checks.value = []
    // A failed run is not "all checks passed"; reset the success summary and
    // surface the reason.
    ran.value = false
    error.value = (err as Error).message
  } finally {
    running.value = false
  }
}

async function runSelftest(target: string) {
  selftesting.value = true
  try {
    selftest.value = await api.system.selftest(target)
  } catch (err) {
    selftest.value = {
      ok: false,
      target,
      mode: 'proxy',
      stage: 'none',
      latency_ms: null,
      status_code: null,
      error: (err as Error).message,
      generated_at: new Date().toISOString(),
    }
  } finally {
    selftesting.value = false
  }
}

async function copyReport() {
  const report = JSON.stringify(
    { generated_at: new Date().toISOString(), checks: checks.value, selftest: selftest.value },
    null,
    2,
  )
  await navigator.clipboard.writeText(report)
}

onMounted(run)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('diagnostics.title')" :subtitle="t('diagnostics.subtitle')">
      <template #actions>
        <NButton secondary :disabled="!checks.length" @click="copyReport">
          <template #icon><Copy :size="15" /></template>
          {{ t('diagnostics.copy') }}
        </NButton>
        <NButton secondary tag="a" :href="api.system.diagnosticsUrl()" target="_blank">
          <template #icon><Download :size="15" /></template>
          {{ t('diagnostics.download') }}
        </NButton>
        <NButton type="primary" :loading="running" @click="run">
          <template #icon><Play :size="15" /></template>
          {{ t('diagnostics.run') }}
        </NButton>
      </template>
    </OPageHeader>

    <div class="summary o-card" :class="{ ok: ran && !issues }">
      <div class="summary-icon">
        <component
          :is="ran && !issues ? CheckCircle2 : Stethoscope"
          :size="26"
          :stroke-width="1.5"
        />
      </div>
      <div>
        <h2>
          {{
            error
              ? t('common.load_failed')
              : running
                ? t('diagnostics.running')
                : !ran
                  ? t('diagnostics.title')
                  : issues
                    ? t('diagnostics.issues', { count: issues })
                    : t('diagnostics.all_pass')
          }}
        </h2>
        <p class="o-small o-muted">{{ error || t('diagnostics.fix_hint') }}</p>
      </div>
      <div class="summary-actions">
        <span v-if="warnCount || failCount" class="o-micro o-subtle">
          {{ t('diagnostics.counts', { warn: warnCount, fail: failCount }) }}
        </span>
        <NButton secondary size="small" @click="router.push('/network')">{{
          t('nav.network')
        }}</NButton>
        <NButton secondary size="small" @click="router.push('/logs')">{{ t('nav.logs') }}</NButton>
      </div>
    </div>

    <section class="selftest o-card">
      <div class="selftest-copy">
        <Wifi :size="18" />
        <div>
          <strong>{{ t('diagnostics.selftest') }}</strong>
          <p class="o-micro o-subtle">{{ t('diagnostics.selftest_hint') }}</p>
        </div>
      </div>
      <div class="selftest-actions">
        <NButton
          v-for="target in ['google', 'huggingface', 'github']"
          :key="target"
          size="small"
          secondary
          :loading="selftesting"
          @click="runSelftest(target)"
        >
          {{ target }}
        </NButton>
      </div>
      <div v-if="selftest" class="selftest-result" :class="selftest.ok ? 'pass' : 'fail'">
        <strong>{{
          selftest.ok ? t('diagnostics.selftest_ok') : t('diagnostics.selftest_fail')
        }}</strong>
        <span class="o-micro">
          {{ selftest.target }} · {{ selftest.mode }} · {{ selftest.stage }} ·
          {{ selftest.latency_ms ?? '—' }} ms
          <template v-if="selftest.status_code"> · HTTP {{ selftest.status_code }}</template>
        </span>
        <small v-if="selftest.error" class="o-micro">{{ selftest.error }}</small>
      </div>
    </section>

    <OEmptyState
      v-if="!ran && !running"
      :title="t('diagnostics.no_checks')"
      :description="t('diagnostics.no_checks')"
    />
    <div v-else class="groups">
      <section v-for="group in groups" :key="group.id" class="group">
        <h2 class="group-title">{{ group.label }}</h2>
        <div class="checks">
          <article
            v-for="check in group.checks"
            :key="check.id"
            class="check o-card"
            :class="check.status"
          >
            <span class="check-icon">
              <component
                :is="
                  check.status === 'pass'
                    ? CheckCircle2
                    : check.status === 'warn'
                      ? CircleAlert
                      : CircleX
                "
                :size="18"
                :stroke-width="1.7"
              />
            </span>
            <div class="check-copy">
              <h3>{{ check.id }}</h3>
              <p>{{ check.message }}</p>
              <small v-if="check.fix">{{ t('diagnostics.fix') }}: {{ check.fix }}</small>
              <small v-if="check.data && Object.keys(check.data).length" class="check-data">
                {{ JSON.stringify(check.data) }}
              </small>
            </div>
            <OStatusPill :status="check.status" size="sm" />
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.summary {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  margin-bottom: 18px;
}
.summary.ok {
  border-color: color-mix(in srgb, var(--success) 28%, var(--border));
  background:
    radial-gradient(360px 160px at 0% 50%, var(--success-soft), transparent 70%), var(--surface);
}
.summary-icon {
  width: 48px;
  height: 48px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 13px;
  background: var(--surface-2);
  color: var(--accent);
}
.summary h2 {
  font-size: 15px;
  font-weight: 600;
}
.summary p {
  margin-top: 2px;
}
.summary-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.checks {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.groups {
  display: grid;
  gap: 18px;
}
.group-title {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-3);
  margin-bottom: 8px;
}
.selftest {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  margin-bottom: 18px;
}
.selftest-copy {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-2);
}
.selftest-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.selftest-result {
  flex-basis: 100%;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.selftest-result.pass strong {
  color: var(--success);
}
.selftest-result.fail strong {
  color: var(--danger);
}
.check-data {
  opacity: 0.7;
  word-break: break-all;
}
.check {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 15px;
}
.check-icon {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--surface-2);
  color: var(--text-3);
}
.check.pass .check-icon {
  color: var(--success);
  background: var(--success-soft);
}
.check.warn .check-icon {
  color: var(--warning);
  background: var(--warning-soft);
}
.check.fail .check-icon {
  color: var(--danger);
  background: var(--danger-soft);
}
.check-copy {
  flex: 1;
  min-width: 0;
}
.check-copy h3 {
  font-size: 12px;
  font-weight: 600;
}
.check-copy p {
  color: var(--text-2);
  font-size: 11px;
  line-height: 1.5;
  margin-top: 2px;
  word-break: break-word;
}
.check-copy small {
  display: block;
  margin-top: 4px;
  color: var(--text-3);
  font-size: 10px;
}
@media (max-width: 900px) {
  .checks {
    grid-template-columns: 1fr;
  }
  .summary {
    flex-wrap: wrap;
  }
  .summary-actions {
    margin-left: 0;
    width: 100%;
  }
}
</style>
