<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NCheckbox, NInput, NModal, NSelect, useDialog, useMessage } from 'naive-ui'
import {
  CalendarClock,
  CloudUpload,
  Plus,
  RefreshCw,
  ShieldCheck,
  ShieldQuestion,
  Trash2,
} from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import OErrorState from '@/components/OErrorState.vue'
import { api } from '@/api'
import type { Certificate } from '@/api/types'
import { formatDate, relativeTime } from '@/utils/format'

const { t, locale } = useI18n()
const message = useMessage()
const dialog = useDialog()

const certificates = ref<Certificate[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const issueOpen = ref(false)
const uploadOpen = ref(false)
const busy = ref<string | null>(null)

const issueForm = ref({ domain: '', method: 'acme', email: '', auto_renew: true, staging: false })
const uploadForm = ref({ domain: '', cert_pem: '', key_pem: '', auto_renew: false })

const methodOptions = computed(() => [
  { label: t('certs.acme'), value: 'acme' },
  { label: t('certs.self_signed'), value: 'self-signed' },
])

async function load() {
  loading.value = true
  try {
    certificates.value = (await api.certificates.list()).certificates
    error.value = null
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

async function issue() {
  if (!issueForm.value.domain.trim()) {
    message.error(t('errors.validation'))
    return
  }
  busy.value = 'issue'
  try {
    const result = await api.certificates.issue(
      issueForm.value.domain.trim(),
      issueForm.value.method as 'acme' | 'self-signed',
      issueForm.value.auto_renew,
      {
        staging: issueForm.value.method === 'acme' ? issueForm.value.staging : undefined,
        email:
          issueForm.value.method === 'acme' ? issueForm.value.email.trim() || undefined : undefined,
      },
    )
    if (result.job_id) {
      message.success(t('certs.acme_started'))
    } else {
      message.success(
        issueForm.value.method === 'acme'
          ? t('certs.acme_started')
          : t('certs.self_signed_created'),
      )
    }
    if (result.warning) message.warning(result.warning)
    issueOpen.value = false
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = null
  }
}

async function upload() {
  if (!uploadForm.value.domain.trim() || !uploadForm.value.cert_pem || !uploadForm.value.key_pem) {
    message.error(t('errors.validation'))
    return
  }
  busy.value = 'upload'
  try {
    const result = await api.certificates.upload(uploadForm.value)
    if (result.warning) message.warning(result.warning)
    message.success(t('certs.uploaded'))
    uploadOpen.value = false
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = null
  }
}

async function renew(certificate: Certificate) {
  busy.value = certificate.id
  try {
    await api.certificates.renew(certificate.id)
    message.success(t('certs.acme_started'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = null
  }
}

async function assign(certificate: Certificate) {
  busy.value = certificate.id
  try {
    const result = await api.certificates.use(certificate.id, ['hysteria2', 'trojan'])
    if (result.warning) message.warning(result.warning)
    message.success(t('certs.use'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = null
  }
}

function remove(certificate: Certificate) {
  dialog.error({
    title: t('common.delete'),
    content: t('certs.delete_confirm', { domain: certificate.domain }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        const result = await api.certificates.remove(certificate.id)
        if (result.warning) message.warning(result.warning)
        message.success(t('common.delete'))
        await load()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

function daysStatus(certificate: Certificate): string {
  const days = certificate.days_remaining ?? 0
  if (days < 0) return 'expired'
  if (days < 14) return 'warning'
  return certificate.status === 'ready' ? 'ready' : certificate.status
}

onMounted(load)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('certs.title')" :subtitle="t('certs.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton secondary @click="uploadOpen = true">
          <template #icon><CloudUpload :size="15" /></template>
          {{ t('certs.upload') }}
        </NButton>
        <NButton type="primary" @click="issueOpen = true">
          <template #icon><Plus :size="16" /></template>
          {{ t('certs.issue') }}
        </NButton>
      </template>
    </OPageHeader>

    <OErrorState v-if="error" :message="error" @retry="load" />

    <div v-else-if="!loading && !certificates.length" class="o-card">
      <OEmptyState
        :title="t('certs.no_certs')"
        :description="t('certs.no_certs_desc')"
        :icon="ShieldCheck"
      >
        <NButton type="primary" @click="issueOpen = true">{{ t('certs.issue') }}</NButton>
        <NButton secondary @click="uploadOpen = true">{{ t('certs.upload') }}</NButton>
      </OEmptyState>
    </div>

    <div v-else class="cert-grid">
      <article v-for="certificate in certificates" :key="certificate.id" class="cert-card o-card">
        <div class="cert-head">
          <span class="domain-icon"><ShieldCheck :size="20" /></span>
          <div class="domain-copy">
            <h2>{{ certificate.domain }}</h2>
            <span class="o-micro o-subtle">{{ certificate.issuer || certificate.source }}</span>
          </div>
          <OStatusPill :status="daysStatus(certificate)" :label="certificate.status" size="sm" />
        </div>

        <div class="cert-ring-row">
          <div
            class="ring"
            :style="{
              '--pct': Math.max(0, Math.min(100, ((certificate.days_remaining ?? 0) / 90) * 100)),
            }"
          >
            <span>{{ certificate.days_remaining ?? '—' }}</span>
            <small>{{ t('common.days') }}</small>
          </div>
          <div class="cert-meta">
            <div>
              <span>{{ t('certs.expires') }}</span><strong>{{
                certificate.expires_at ? formatDate(certificate.expires_at, locale) : '—'
              }}</strong>
            </div>
            <div>
              <span>{{ t('certs.source') }}</span><strong>{{ certificate.source }}</strong>
            </div>
            <div>
              <span>{{ t('certs.auto_renew') }}</span><strong>{{
                certificate.auto_renew ? t('common.yes') : t('common.no')
              }}</strong>
            </div>
            <div>
              <span>{{ t('common.created_at') }}</span><strong>{{
                relativeTime(certificate.created_at, locale)
              }}</strong>
            </div>
          </div>
        </div>

        <p v-if="certificate.last_error" class="cert-error">{{ certificate.last_error }}</p>

        <footer class="cert-actions">
          <NButton
            size="small"
            secondary
            :loading="busy === certificate.id"
            @click="assign(certificate)"
          >
            <template #icon><ShieldCheck :size="14" /></template>
            {{ t('certs.use') }}
          </NButton>
          <NButton
            v-if="certificate.source === 'acme'"
            size="small"
            secondary
            :loading="busy === certificate.id"
            @click="renew(certificate)"
          >
            <template #icon><CalendarClock :size="14" /></template>
            {{ t('certs.renew') }}
          </NButton>
          <NButton size="small" quaternary type="error" @click="remove(certificate)">
            <template #icon><Trash2 :size="14" /></template>
            {{ t('common.delete') }}
          </NButton>
        </footer>
      </article>
    </div>

    <NModal
      v-model:show="issueOpen"
      preset="card"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('certs.issue') }}</template>
      <div class="form">
        <label class="field">
          <span>{{ t('certs.domain') }}</span>
          <NInput v-model:value="issueForm.domain" placeholder="vpn.example.com" />
          <small class="o-subtle">{{ t('certs.domain_hint') }}</small>
        </label>
        <label class="field">
          <span>{{ t('common.type') }}</span>
          <NSelect v-model:value="issueForm.method" :options="methodOptions" />
        </label>
        <label v-if="issueForm.method === 'acme'" class="field">
          <span>{{ t('certs.email') }}</span>
          <NInput v-model:value="issueForm.email" placeholder="you@example.com" />
        </label>
        <label v-if="issueForm.method === 'acme'" class="field row">
          <NCheckbox v-model:checked="issueForm.auto_renew">{{ t('certs.auto_renew') }}</NCheckbox>
          <NCheckbox v-model:checked="issueForm.staging">{{ t('certs.staging') }}</NCheckbox>
        </label>
        <div v-if="issueForm.method === 'self-signed'" class="hint-box">
          <ShieldQuestion :size="15" />
          <span>{{ t('certs.self_signed') }} — {{ t('inbounds.requires_cert') }}</span>
        </div>
      </div>
      <template #footer>
        <div class="modal-actions">
          <NButton secondary @click="issueOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="busy === 'issue'" @click="issue">{{
            t('certs.issue')
          }}</NButton>
        </div>
      </template>
    </NModal>

    <NModal
      v-model:show="uploadOpen"
      preset="card"
      :style="{ width: 'min(620px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('certs.upload') }}</template>
      <div class="form">
        <label class="field">
          <span>{{ t('certs.domain') }}</span>
          <NInput v-model:value="uploadForm.domain" placeholder="vpn.example.com" />
        </label>
        <label class="field">
          <span>{{ t('certs.cert_pem') }}</span>
          <NInput
            v-model:value="uploadForm.cert_pem"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 8 }"
          />
        </label>
        <label class="field">
          <span>{{ t('certs.key_pem') }}</span>
          <NInput
            v-model:value="uploadForm.key_pem"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 8 }"
          />
        </label>
        <p class="o-micro o-subtle">{{ t('certs.upload_renew_hint') }}</p>
      </div>
      <template #footer>
        <div class="modal-actions">
          <NButton secondary @click="uploadOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="busy === 'upload'" @click="upload">{{
            t('common.upload')
          }}</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.cert-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.cert-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.cert-head {
  display: flex;
  align-items: flex-start;
  gap: 11px;
}
.domain-icon {
  width: 40px;
  height: 40px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: var(--success);
  background: var(--success-soft);
}
.domain-copy {
  flex: 1;
  min-width: 0;
}
.domain-copy h2 {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cert-ring-row {
  display: flex;
  gap: 18px;
  align-items: center;
}
.ring {
  --pct: 60;
  width: 92px;
  height: 92px;
  border-radius: 50%;
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(closest-side, var(--surface) 78%, transparent 79% 100%),
    conic-gradient(var(--success) calc(var(--pct) * 1%), var(--surface-2) 0);
  border: 1px solid var(--border);
}
.ring span {
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.ring small {
  font-size: 9px;
  color: var(--text-3);
}
.cert-meta {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 14px;
}
.cert-meta div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.cert-meta span {
  color: var(--text-3);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.cert-meta strong {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-2);
}
.cert-error {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 10.5px;
  line-height: 1.5;
}
.cert-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.form {
  display: flex;
  flex-direction: column;
  gap: 15px;
}
.form .row {
  flex-direction: row;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field > span {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
}
.field small {
  line-height: 1.5;
}
.hint-box {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 9px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 11px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
@media (max-width: 1000px) {
  .cert-grid {
    grid-template-columns: 1fr;
  }
}
</style>
