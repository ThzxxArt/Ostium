<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton, NSwitch, useDialog, useMessage } from 'naive-ui'
import {
  Cable,
  KeyRound,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  ShieldQuestion,
  Waypoints,
  Zap,
} from 'lucide-vue-next'
import OPageHeader from '@/components/OPageHeader.vue'
import OCopyButton from '@/components/OCopyButton.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import OErrorState from '@/components/OErrorState.vue'
import { api } from '@/api'
import type { Inbound } from '@/api/types'

const { t } = useI18n()
const router = useRouter()
const dialog = useDialog()
const message = useMessage()

const inbounds = ref<Inbound[]>([])
const loading = ref(true)
const busy = ref<string | null>(null)
const error = ref<string | null>(null)
const warning = ref<string | null>(null)

const meta: Record<
  string,
  { title: string; description: string; icon: unknown; accent: string; badge: string }
> = {
  vless: {
    title: 'inbounds.reality',
    description: 'inbounds.reality_desc',
    icon: ShieldCheck,
    accent: 'mint',
    badge: 'TCP 443',
  },
  hysteria2: {
    title: 'inbounds.hysteria2',
    description: 'inbounds.hysteria2_desc',
    icon: Zap,
    accent: 'blue',
    badge: 'UDP 443',
  },
  trojan: {
    title: 'inbounds.trojan',
    description: 'inbounds.trojan_desc',
    icon: LockKeyhole,
    accent: 'violet',
    badge: 'TCP 443',
  },
  shadowsocks: {
    title: 'inbounds.shadowsocks',
    description: 'inbounds.shadowsocks_desc',
    icon: Cable,
    accent: 'amber',
    badge: '8388',
  },
}

const enabledCount = computed(() => inbounds.value.filter((item) => item.enabled).length)

async function load() {
  loading.value = true
  try {
    inbounds.value = (await api.inbounds.list()).inbounds
    error.value = null
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

async function toggle(inbound: Inbound, enabled: boolean) {
  busy.value = inbound.kind
  warning.value = null
  try {
    const result = await api.inbounds.update(inbound.kind, { enabled })
    if (result.warning) warning.value = result.warning
    message.success(enabled ? t('inbounds.enabled') : t('inbounds.disabled'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = null
  }
}

function confirmRotate(inbound: Inbound) {
  dialog.warning({
    title: t('inbounds.rotate_keys'),
    content: t('inbounds.rotate_confirm'),
    positiveText: t('common.confirm'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      busy.value = inbound.kind
      try {
        const result = await api.inbounds.rotateReality('vless')
        if (result.warning) warning.value = result.warning
        message.success(t('inbounds.rotate_keys'))
        await load()
      } catch (err) {
        message.error((err as Error).message)
      } finally {
        busy.value = null
      }
    },
  })
}

function protocolIcon(inbound: Inbound) {
  return meta[inbound.kind]?.icon || Waypoints
}

onMounted(load)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('inbounds.title')" :subtitle="t('inbounds.subtitle')">
      <template #actions>
        <span class="o-muted o-small"
          >{{ enabledCount }} / {{ inbounds.length }} {{ t('common.enabled') }}</span
        >
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton type="primary" @click="router.push('/certificates')">
          <template #icon><ShieldCheck :size="16" /></template>
          {{ t('certs.title') }}
        </NButton>
      </template>
    </OPageHeader>

    <div v-if="warning" class="banner warning" role="status">
      <ShieldQuestion :size="16" />
      <span>{{ t('inbounds.apply_warning', { message: warning }) }}</span>
    </div>

    <OErrorState v-if="error && !inbounds.length" :message="error" @retry="load" />

    <div v-else-if="!inbounds.length && !loading" class="o-card">
      <OEmptyState :title="t('common.empty')" :description="t('inbounds.subtitle')" />
    </div>

    <div v-else class="inbound-grid">
      <article
        v-for="inbound in inbounds"
        :key="inbound.id"
        class="inbound-card"
        :class="[`accent-${meta[inbound.kind]?.accent || 'mint'}`, { enabled: inbound.enabled }]"
      >
        <header class="card-head">
          <div class="protocol">
            <span class="protocol-icon"
              ><component :is="protocolIcon(inbound)" :size="21" :stroke-width="1.6"
            /></span>
            <div>
              <div class="title-row">
                <h2>{{ t(meta[inbound.kind]?.title || 'inbounds.title') }}</h2>
                <span class="badge">{{ meta[inbound.kind]?.badge }}</span>
              </div>
              <p class="o-small o-muted">{{ t(meta[inbound.kind]?.description || '') }}</p>
            </div>
          </div>
          <div class="switch-wrap">
            <OStatusPill
              :status="inbound.enabled ? 'connected' : 'disabled'"
              :label="inbound.enabled ? t('common.enabled') : t('common.disabled')"
              size="sm"
            />
            <NSwitch
              :value="inbound.enabled"
              :loading="busy === inbound.kind"
              :aria-label="inbound.kind"
              @update:value="(value: boolean) => toggle(inbound, value)"
            />
          </div>
        </header>

        <div class="details">
          <div class="detail">
            <span>{{ t('inbounds.port') }}</span>
            <strong class="o-mono">{{ inbound.port }}</strong>
          </div>
          <div class="detail">
            <span>{{ t('common.status') }}</span>
            <strong>{{ inbound.listen }}:{{ inbound.port }}</strong>
          </div>
          <template v-if="inbound.kind === 'vless'">
            <div class="detail wide">
              <span>{{ t('inbounds.server_name') }}</span>
              <strong class="o-mono">{{ inbound.params.server_name || '—' }}</strong>
            </div>
            <div class="detail wide">
              <span>{{ t('inbounds.handshake') }}</span>
              <strong class="o-mono"
                >{{ inbound.params.handshake_server || '—' }}:{{
                  inbound.params.handshake_port || 443
                }}</strong
              >
            </div>
            <div class="detail wide">
              <span>{{ t('inbounds.public_key') }}</span>
              <div class="copy-row">
                <code class="o-mono o-truncate">{{ inbound.params.public_key || '—' }}</code>
                <OCopyButton
                  v-if="inbound.params.public_key"
                  :value="inbound.params.public_key"
                  size="tiny"
                />
              </div>
            </div>
            <div class="detail wide">
              <span>{{ t('inbounds.short_id') }}</span>
              <div class="copy-row">
                <code class="o-mono">{{ inbound.params.short_id || '—' }}</code>
                <OCopyButton
                  v-if="inbound.params.short_id"
                  :value="inbound.params.short_id"
                  size="tiny"
                />
              </div>
            </div>
          </template>
          <div v-if="inbound.requires_certificate" class="detail wide">
            <span>{{ t('inbounds.certificate') }}</span>
            <div class="cert-state">
              <template v-if="inbound.certificate">
                <ShieldCheck :size="14" class="ok" />
                <strong>{{ inbound.certificate.domain }}</strong>
                <span class="o-micro o-subtle">{{
                  t('certs.days_left', { days: inbound.certificate.days_remaining ?? 0 })
                }}</span>
              </template>
              <template v-else>
                <ShieldQuestion :size="14" class="warn" />
                <strong>{{ t('inbounds.no_certificate') }}</strong>
                <NButton text type="primary" size="tiny" @click="router.push('/certificates')">
                  {{ t('certs.issue') }}
                </NButton>
              </template>
            </div>
          </div>
        </div>

        <footer class="card-foot">
          <p v-if="inbound.requires_certificate && !inbound.certificate" class="warn-text">
            {{ t('inbounds.requires_cert') }}
          </p>
          <p v-else-if="inbound.kind === 'vless' && inbound.enabled" class="o-micro o-subtle">
            {{ t('inbounds.mutual_exclusion') }}
          </p>
          <span v-else />
          <NButton
            v-if="inbound.kind === 'vless'"
            size="small"
            secondary
            :loading="busy === 'vless'"
            @click="confirmRotate(inbound)"
          >
            <template #icon><KeyRound :size="14" /></template>
            {{ t('inbounds.rotate_keys') }}
          </NButton>
        </footer>
      </article>
    </div>
  </div>
</template>

<style scoped>
.banner {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 12px;
  margin-bottom: 18px;
}
.inbound-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.inbound-card {
  --accent-local: var(--accent);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-1);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: relative;
  overflow: hidden;
}
.inbound-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  background: linear-gradient(90deg, var(--accent-local), transparent 70%);
  opacity: 0.5;
}
.inbound-card.accent-blue {
  --accent-local: var(--info);
}
.inbound-card.accent-violet {
  --accent-local: #a78bfa;
}
.inbound-card.accent-amber {
  --accent-local: var(--warning);
}
.inbound-card:not(.enabled) {
  opacity: 0.86;
}
.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.protocol {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  min-width: 0;
}
.protocol-icon {
  width: 42px;
  height: 42px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 12px;
  color: var(--accent-local);
  background: color-mix(in srgb, var(--accent-local) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent-local) 22%, transparent);
}
.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
h2 {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.badge {
  font-size: 9px;
  font-family: var(--font-mono);
  color: var(--text-3);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 1px 5px;
}
.protocol p {
  margin-top: 2px;
}
.switch-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
.details {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
  padding: 14px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg) 42%, transparent);
  border: 1px solid var(--border);
}
.detail {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.detail span {
  color: var(--text-3);
  font-size: 10px;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.detail strong {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
}
.detail.wide {
  grid-column: 1 / -1;
}
.copy-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.copy-row code {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cert-state {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  font-size: 12px;
}
.cert-state .ok {
  color: var(--success);
}
.cert-state .warn {
  color: var(--warning);
}
.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: auto;
}
.warn-text {
  color: var(--warning);
  font-size: 10.5px;
}
@media (max-width: 1100px) {
  .inbound-grid {
    grid-template-columns: 1fr;
  }
}
</style>
