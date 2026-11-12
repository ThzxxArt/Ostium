<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton } from 'naive-ui'
import { CheckCircle2, CircleAlert, CircleX, Play, Stethoscope } from 'lucide-vue-next'
import OPageHeader from '@/components/OPageHeader.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { DoctorCheck } from '@/api/types'

const { t } = useI18n()
const router = useRouter()

const checks = ref<DoctorCheck[]>([])
const running = ref(false)
const ran = ref(false)

const issues = computed(() => checks.value.filter((check) => check.status !== 'pass').length)

async function run() {
  running.value = true
  try {
    checks.value = (await api.system.doctor()).checks
    ran.value = true
  } catch {
    checks.value = []
  } finally {
    running.value = false
  }
}

onMounted(run)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('diagnostics.title')" :subtitle="t('diagnostics.subtitle')">
      <template #actions>
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
            running
              ? t('diagnostics.running')
              : !ran
                ? t('diagnostics.title')
                : issues
                  ? t('diagnostics.issues', { count: issues })
                  : t('diagnostics.all_pass')
          }}
        </h2>
        <p class="o-small o-muted">{{ t('diagnostics.fix_hint') }}</p>
      </div>
      <div class="summary-actions">
        <NButton secondary size="small" @click="router.push('/network')">{{
          t('nav.network')
        }}</NButton>
        <NButton secondary size="small" @click="router.push('/logs')">{{ t('nav.logs') }}</NButton>
      </div>
    </div>

    <OEmptyState
      v-if="!ran && !running"
      :title="t('diagnostics.no_checks')"
      :description="t('diagnostics.no_checks')"
    />
    <div v-else class="checks">
      <article v-for="check in checks" :key="check.id" class="check o-card" :class="check.status">
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
        </div>
        <OStatusPill :status="check.status" size="sm" />
      </article>
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
