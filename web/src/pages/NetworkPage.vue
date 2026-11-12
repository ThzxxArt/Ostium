<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NSwitch, useMessage } from 'naive-ui'
import {
  Check,
  Globe2,
  Info,
  Router,
  ShieldCheck,
  Terminal,
  Waypoints,
  Wifi,
} from 'lucide-vue-next'
import OPageHeader from '@/components/OPageHeader.vue'
import OSectionCard from '@/components/OSectionCard.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import { api } from '@/api'
import type { SystemInfo } from '@/api/types'
import { useCopy } from '@/composables/useCopy'

const { t } = useI18n()
const message = useMessage()
const { copy } = useCopy()

const info = ref<SystemInfo | null>(null)
const loading = ref(true)
const busy = ref<string | null>(null)
const lanBusy = ref(false)

const mode = computed(() => info.value?.mode || 'mixed')
const proxy = computed(() => info.value?.proxy)
const tun = computed(() => info.value?.tun)
const allowLan = computed(() => Boolean(info.value?.allow_lan))
const lanPort = computed(() => info.value?.lan_port || 7890)
const lanAddresses = computed(() => info.value?.lan_addresses ?? [])
const lanAvailable = computed(() => mode.value !== 'tun')
const proxyHost = computed(() => (allowLan.value ? '0.0.0.0' : '127.0.0.1'))

const modes = computed(() => [
  {
    id: 'mixed' as const,
    title: t('network.mixed'),
    description: t('network.mixed_desc'),
    icon: Waypoints,
    active: mode.value === 'mixed',
    enabled: true,
  },
  {
    id: 'system_proxy' as const,
    title: t('network.system'),
    description: t('network.system_desc'),
    icon: Globe2,
    active: mode.value === 'system_proxy',
    enabled: proxy.value?.supported ?? false,
  },
  {
    id: 'tun' as const,
    title: t('network.tun'),
    description: t('network.tun_desc'),
    icon: ShieldCheck,
    active: mode.value === 'tun',
    enabled: true,
  },
])

const envHint = computed(
  () =>
    `export http_proxy=http://127.0.0.1:7890\nexport https_proxy=http://127.0.0.1:7890\nexport all_proxy=socks5://127.0.0.1:7890`,
)

async function load() {
  loading.value = true
  try {
    info.value = await api.system.info()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function toggleLan(value: boolean) {
  if (lanBusy.value) return
  lanBusy.value = true
  try {
    await api.settings.update({ allow_lan: value })
    message.success(value ? t('network.lan_enabled') : t('network.lan_disabled'))
    await load()
  } catch (err) {
    message.error(t('network.lan_failed', { message: (err as Error).message }))
  } finally {
    lanBusy.value = false
  }
}

function copyLan() {
  const address = lanAddresses.value[0]
  const host = address || t('network.lan_placeholder')
  void copy(`${host}:${lanPort.value}`)
}

async function switchMode(id: string) {
  if (busy.value) return
  busy.value = id
  try {
    await api.system.mode(id)
    message.success(t('network.switched'))
    await load()
  } catch (err) {
    message.error(t('network.failed', { message: (err as Error).message }))
  } finally {
    busy.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('network.title')" :subtitle="t('network.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">{{ t('common.refresh') }}</NButton>
      </template>
    </OPageHeader>

    <div class="mode-grid">
      <article
        v-for="item in modes"
        :key="item.id"
        class="mode-card o-card"
        :class="{ active: item.active, unsupported: !item.enabled }"
      >
        <div class="mode-head">
          <span class="mode-icon"
            ><component :is="item.icon" :size="22" :stroke-width="1.6"
          /></span>
          <OStatusPill
            v-if="item.active"
            status="connected"
            :label="t('network.current')"
            size="sm"
          />
        </div>
        <h2>{{ item.title }}</h2>
        <p>{{ item.description }}</p>
        <div class="mode-foot">
          <span v-if="!item.enabled" class="unsupported-text">{{
            t('network.system_proxy_unsupported')
          }}</span>
          <span v-else-if="item.active" class="active-text"
            ><Check :size="13" /> {{ t('network.current') }}</span
          >
          <span v-else />
          <NButton
            size="small"
            :type="item.active ? 'default' : 'primary'"
            :secondary="item.active"
            :disabled="!item.enabled"
            :loading="busy === item.id"
            @click="switchMode(item.id)"
          >
            {{ item.active ? t('common.enabled') : t('network.enable') }}
          </NButton>
        </div>
      </article>
    </div>

    <div class="split">
      <OSectionCard :title="t('network.current')" :icon="Wifi">
        <div class="detail-grid">
          <div>
            <span>{{ t('network.port') }}</span><strong class="o-mono"
              >{{ proxyHost }}:{{ lanPort }}</strong
            >
          </div>
          <div>
            <span>{{ t('network.tun_interface') }}</span><strong class="o-mono">{{
              tun?.interface || 'ostium0'
            }}</strong>
          </div>
          <div>
            <span>{{ t('network.mtu') }}</span><strong>{{ tun?.mtu || 1500 }}</strong>
          </div>
          <div>
            <span>{{ t('network.stack') }}</span><strong>{{ tun?.stack || 'gvisor' }}</strong>
          </div>
          <div>
            <span>{{ t('network.ipv6') }}</span><strong>{{ t('common.yes') }}</strong>
          </div>
          <div>
            <span>{{ t('network.strict_route') }}</span><strong>{{ t('common.yes') }}</strong>
          </div>
          <div>
            <span>{{ t('network.dns_hijack') }}</span><strong>{{ t('common.yes') }}</strong>
          </div>
          <div>
            <span>{{ t('common.status') }}</span><strong>{{
              proxy?.enabled ? t('common.enabled') : t('common.disabled')
            }}</strong>
          </div>
        </div>
        <p class="note">{{ t('home.tun_warning') }}</p>
      </OSectionCard>

      <OSectionCard :title="t('network.env_hint')" :icon="Terminal">
        <p class="o-small o-muted">{{ t('network.mixed_desc') }}</p>
        <pre class="o-pre env">{{ envHint }}</pre>
        <div class="env-actions">
          <NButton size="small" secondary @click="copy(envHint)">{{ t('common.copy') }}</NButton>
        </div>
        <p class="note">{{ t('home.mixed_warning') }}</p>
      </OSectionCard>
    </div>

    <OSectionCard :title="t('network.lan')" :icon="Router" class="lan-card">
      <div class="lan-head">
        <div>
          <strong>{{ t('network.allow_lan') }}</strong>
          <p class="o-small o-muted">{{ t('network.allow_lan_hint') }}</p>
        </div>
        <NSwitch
          :value="allowLan"
          :loading="lanBusy"
          :disabled="!lanAvailable"
          @update:value="toggleLan"
        />
      </div>
      <div v-if="allowLan && lanAvailable" class="lan-body">
        <p class="o-small o-muted">{{ t('network.lan_addresses') }}</p>
        <div class="lan-addresses">
          <code v-for="address in lanAddresses" :key="address">{{ address }}:{{ lanPort }}</code>
          <code v-if="!lanAddresses.length">{{ t('network.lan_placeholder') }}:{{ lanPort }}</code>
        </div>
        <NButton size="small" secondary @click="copyLan">{{ t('common.copy') }}</NButton>
        <p class="note">{{ t('network.lan_warning') }}</p>
      </div>
      <p v-else class="note">
        {{ lanAvailable ? t('network.allow_lan_off') : t('network.lan_tun') }}
      </p>
    </OSectionCard>

    <div class="tip o-card">
      <Info :size="17" />
      <div>
        <strong>{{ t('network.system') }} / {{ t('network.tun') }}</strong>
        <p>{{ t('network.system_proxy_unsupported') }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lan-card {
  margin-top: 20px;
}
.lan-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}
.lan-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 16px;
}
.lan-addresses {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.lan-addresses code {
  padding: 5px 9px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 12px;
}
.mode-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}
.mode-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 9px;
  min-height: 220px;
}
.mode-card.active {
  border-color: color-mix(in srgb, var(--accent) 42%, transparent);
  background:
    radial-gradient(320px 200px at 20% 0%, rgba(94, 234, 212, 0.1), transparent 70%), var(--surface);
}
.mode-card.unsupported {
  opacity: 0.72;
}
.mode-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mode-icon {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
}
h2 {
  font-size: 15px;
  font-weight: 600;
}
p {
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.55;
  flex: 1;
}
.mode-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 8px;
}
.active-text {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--success);
  font-size: 10.5px;
}
.unsupported-text {
  color: var(--warning);
  font-size: 10px;
  line-height: 1.4;
}
.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 18px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.detail-grid div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.detail-grid span {
  color: var(--text-3);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.detail-grid strong {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-2);
}
.note {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  color: var(--text-3);
  font-size: 10px;
  line-height: 1.55;
}
.env {
  margin-top: 10px;
  font-size: 11px;
}
.env-actions {
  margin-top: 8px;
}
.tip {
  margin-top: 18px;
  display: flex;
  gap: 11px;
  padding: 14px 16px;
  color: var(--text-2);
}
.tip strong {
  display: block;
  font-size: 11.5px;
  color: var(--text);
}
.tip p {
  font-size: 10.5px;
  line-height: 1.55;
  margin-top: 2px;
}
@media (max-width: 1000px) {
  .mode-grid,
  .split {
    grid-template-columns: 1fr;
  }
}
</style>
