<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NButton,
  NCheckbox,
  NCheckboxGroup,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSwitch,
  useDialog,
  useMessage,
} from 'naive-ui'
import QrcodeVue from 'qrcode.vue'
import {
  Bell,
  Database,
  Globe2,
  KeyRound,
  LockKeyhole,
  Moon,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Sun,
  Trash2,
  Wrench,
} from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OSectionCard from '@/components/OSectionCard.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OCopyButton from '@/components/OCopyButton.vue'
import OQrModal from '@/components/OQrModal.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { AppSettings, Backup, Certificate } from '@/api/types'
import { formatBytes, formatDate } from '@/utils/format'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useBrowserNotifications } from '@/composables/useBrowserNotifications'

const { t, locale } = useI18n()
const message = useMessage()
const dialog = useDialog()
const app = useAppStore()
const auth = useAuthStore()
const browserNotifications = useBrowserNotifications()

const settings = ref<AppSettings | null>(null)
const certificates = ref<Certificate[]>([])
const backups = ref<Backup[]>([])
const loading = ref(true)
const saving = ref(false)
const activeTab = ref('general')

const general = ref({
  log_level: 'info',
  mixed_port: 7890,
  auto_connect: false,
  auto_reconnect: true,
  public_base_url: '',
  acme_email: '',
  acme_staging: false,
  block_private_egress: true,
})
const notifications = ref({ webhook_url: '', webhook_secret: '', enabled: true })
const clearWebhookSecret = ref(false)
const maintenance = ref({
  update_channel: 'stable',
  audit_retention_days: 90,
  traffic_retention_days: 365,
  job_retention_days: 7,
  auto_backup: false,
})
const allowlist = ref('')
const publicUiDomain = ref('')
const publicUiEnabled = ref(false)

const passwordForm = ref({ current: '', next: '', confirm: '' })
const totpStart = ref<{ secret: string; uri: string; recovery_codes: string[] } | null>(null)
const totpModal = ref(false)
const totpCode = ref('')
const qrOpen = ref(false)
const qrValue = ref('')
const disablingTotp = ref(false)
const disableTotpOpen = ref(false)
const disableTotpPassword = ref('')

const tokenOpen = ref(false)
const tokenName = ref('')
const tokenScopes = ref(['read', 'write'])
const newToken = ref<string | null>(null)
const restoring = ref<Backup | null>(null)
const restorePassword = ref('')
const restoreOpen = ref(false)
const backupPassword = ref('')
const backupAck = ref(false)
const backupOpen = ref(false)

const server = computed(() => auth.isServer)
const logLevels = [
  { label: 'Debug', value: 'debug' },
  { label: 'Info', value: 'info' },
  { label: 'Warning', value: 'warning' },
  { label: 'Error', value: 'error' },
]
const certDomains = computed(() =>
  certificates.value
    .filter((certificate) => certificate.status === 'ready')
    .map((certificate) => ({ label: certificate.domain, value: certificate.domain })),
)
const apiTokens = computed<Array<Record<string, unknown>>>(() =>
  (settings.value?.security.api_tokens ?? []).filter((token) => !token.revoked),
)

async function load() {
  loading.value = true
  try {
    const [data, certData, backupData] = await Promise.all([
      api.settings.get(),
      server.value ? api.certificates.list() : Promise.resolve({ certificates: [] }),
      api.backups.list(),
    ])
    settings.value = data
    certificates.value = certData.certificates
    backups.value = backupData.backups
    general.value = {
      log_level: data.general.log_level,
      mixed_port: data.general.mixed_port,
      auto_connect: data.general.auto_connect,
      auto_reconnect: data.general.auto_reconnect,
      public_base_url: data.general.public_base_url || '',
      acme_email: data.general.acme_email || '',
      acme_staging: data.general.acme_staging,
      block_private_egress: data.general.block_private_egress,
    }
    notifications.value = {
      webhook_url: data.notifications.webhook_url || '',
      webhook_secret: '',
      enabled: data.notifications.enabled,
    }
    clearWebhookSecret.value = false
    maintenance.value = {
      update_channel: data.maintenance.update_channel,
      audit_retention_days: data.maintenance.audit_retention_days,
      traffic_retention_days: data.maintenance.traffic_retention_days,
      job_retention_days: data.maintenance.job_retention_days,
      auto_backup: data.maintenance.auto_backup,
    }
    allowlist.value = (data.security.ui_allowlist || []).join(', ')
    publicUiEnabled.value = data.general.public_ui
    publicUiDomain.value = data.general.domain || ''
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function saveGeneral() {
  saving.value = true
  try {
    const result = await api.settings.update({
      log_level: general.value.log_level,
      mixed_port: general.value.mixed_port,
      auto_connect: general.value.auto_connect,
      auto_reconnect: general.value.auto_reconnect,
      public_base_url: general.value.public_base_url || null,
      acme_email: general.value.acme_email || null,
      acme_staging: general.value.acme_staging,
      block_private_egress: general.value.block_private_egress,
    })
    if (result.warning) message.warning(result.warning)
    message.success(t('settings.saved'))
    if (result.restart_required) message.warning(t('settings.restart_hint'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    saving.value = false
  }
}

async function saveNotifications() {
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      webhook_url: notifications.value.webhook_url || null,
      notifications_enabled: notifications.value.enabled,
    }
    if (clearWebhookSecret.value) payload.webhook_secret = null
    else if (notifications.value.webhook_secret) {
      payload.webhook_secret = notifications.value.webhook_secret
    }
    await api.settings.update(payload)
    message.success(t('settings.saved'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    saving.value = false
  }
}

async function enableBrowserNotifications() {
  const ok = await browserNotifications.request()
  if (ok) message.success(t('notify.enable_browser'))
  else message.error(t('notify.browser_denied'))
}

async function saveMaintenance() {
  saving.value = true
  try {
    await api.settings.update(maintenance.value)
    message.success(t('settings.saved'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    saving.value = false
  }
}

async function saveAllowlist() {
  saving.value = true
  try {
    const entries = allowlist.value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
    await api.settings.update({ ui_allowlist: entries })
    message.success(t('settings.saved'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    saving.value = false
  }
}

async function togglePublicUi(value: boolean) {
  if (value && !auth.totpEnabled) {
    message.error(t('certs.enable_totp_first'))
    publicUiEnabled.value = false
    return
  }
  if (value && !publicUiDomain.value) {
    message.error(t('certs.domain_hint'))
    publicUiEnabled.value = false
    return
  }
  try {
    const result = await api.settings.publicUi(value, publicUiDomain.value || undefined)
    message.success(result.message)
    await load()
  } catch (err) {
    publicUiEnabled.value = !value
    message.error((err as Error).message)
  }
}

async function changePassword() {
  if (passwordForm.value.next.length < 10) {
    message.error(t('auth.password_too_short'))
    return
  }
  if (passwordForm.value.next !== passwordForm.value.confirm) {
    message.error(t('auth.password_mismatch'))
    return
  }
  try {
    await api.auth.changePassword(passwordForm.value.current, passwordForm.value.next)
    passwordForm.value = { current: '', next: '', confirm: '' }
    message.success(t('auth.password_changed'))
  } catch (err) {
    message.error((err as Error).message)
  }
}

async function startTotp() {
  try {
    totpStart.value = await api.auth.totpStart()
    totpModal.value = true
  } catch (err) {
    message.error((err as Error).message)
  }
}

async function confirmTotp() {
  try {
    await api.auth.totpConfirm(totpCode.value)
    totpModal.value = false
    totpCode.value = ''
    message.success(t('auth.totp_enabled'))
    await auth.refresh()
  } catch (err) {
    message.error((err as Error).message)
  }
}

async function cancelTotp() {
  totpModal.value = false
  totpStart.value = null
  totpCode.value = ''
  try {
    await api.auth.totpCancel()
  } catch {
    // The pending secret expires automatically; there is nothing else to do.
  }
}

function disableTotp() {
  disableTotpPassword.value = ''
  disableTotpOpen.value = true
}

async function confirmDisableTotp() {
  if (!disableTotpPassword.value) return
  disablingTotp.value = true
  try {
    await api.auth.totpDisable(disableTotpPassword.value)
    disableTotpOpen.value = false
    disableTotpPassword.value = ''
    message.success(t('auth.totp_disabled'))
    await auth.refresh()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    disablingTotp.value = false
  }
}

async function createToken() {
  if (!tokenName.value.trim()) return
  try {
    const result = await api.settings.createToken(tokenName.value, tokenScopes.value)
    newToken.value = result.token
    tokenName.value = ''
    tokenOpen.value = false
    await load()
  } catch (err) {
    message.error((err as Error).message)
  }
}

function revokeToken(id: string) {
  dialog.warning({
    title: t('common.revoke'),
    content: t('settings.revoke_confirm'),
    positiveText: t('common.confirm'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.settings.revokeToken(id)
        await load()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

async function createBackup() {
  try {
    const result = await api.backups.create(
      backupPassword.value || undefined,
      backupPassword.value ? false : backupAck.value,
    )
    backupOpen.value = false
    backupPassword.value = ''
    backupAck.value = false
    app.jobDrawerOpen = true
    message.success(t('common.queued') + `: ${result.job_id.slice(0, 8)}`)
    await load()
  } catch (err) {
    message.error((err as Error).message)
  }
}

function restore(backup: Backup) {
  restoring.value = backup
  restorePassword.value = ''
  restoreOpen.value = true
}

async function confirmRestore() {
  if (!restoring.value) return
  try {
    const result = await api.backups.restore(restoring.value.id, restorePassword.value || undefined)
    restoreOpen.value = false
    message.warning(result.message)
  } catch (err) {
    message.error((err as Error).message)
  }
}

function removeBackup(backup: Backup) {
  dialog.warning({
    title: t('common.delete'),
    content: t('common.delete_confirm'),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.backups.remove(backup.id)
        await load()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

function showQr(value: string) {
  qrValue.value = value
  qrOpen.value = true
}

onMounted(load)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('settings.title')" :subtitle="t('settings.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
      </template>
    </OPageHeader>

    <div v-if="settings" class="settings-layout">
      <nav class="settings-nav o-card" :aria-label="t('settings.sections')">
        <button
          v-for="tab in ['general', 'security', 'notifications', 'maintenance']"
          :key="tab"
          type="button"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >
          <component
            :is="
              {
                general: Wrench,
                security: ShieldCheck,
                notifications: Bell,
                maintenance: Database,
              }[tab]
            "
            :size="16"
          />
          <span>{{ t(`settings.${tab}`) }}</span>
        </button>
      </nav>

      <div class="settings-content">
        <template v-if="activeTab === 'general'">
          <OSectionCard :title="t('settings.general')" :icon="Wrench">
            <div class="form-grid">
              <label class="field">
                <span>{{ t('settings.language') }}</span>
                <div class="segmented">
                  <button
                    type="button"
                    :class="{ active: app.locale.startsWith('zh') }"
                    @click="app.locale.startsWith('zh') ? null : app.toggleLanguage()"
                  >
                    中文
                  </button>
                  <button
                    type="button"
                    :class="{ active: app.locale.startsWith('en') }"
                    @click="app.locale.startsWith('en') ? null : app.toggleLanguage()"
                  >
                    English
                  </button>
                </div>
                <small class="o-subtle">{{ t('settings.language_hint') }}</small>
              </label>
              <label class="field">
                <span>{{ t('settings.theme') }}</span>
                <div class="segmented">
                  <button
                    type="button"
                    :class="{ active: app.theme === 'dark' }"
                    @click="app.setTheme('dark')"
                  >
                    <Moon :size="13" /> {{ t('settings.theme_dark') }}
                  </button>
                  <button
                    type="button"
                    :class="{ active: app.theme === 'light' }"
                    @click="app.setTheme('light')"
                  >
                    <Sun :size="13" /> {{ t('settings.theme_light') }}
                  </button>
                  <button
                    type="button"
                    :class="{ active: app.theme === 'system' }"
                    @click="app.setTheme('system')"
                  >
                    {{ t('settings.theme_system') }}
                  </button>
                </div>
              </label>
              <label class="field">
                <span>{{ t('settings.log_level') }}</span>
                <NSelect v-model:value="general.log_level" :options="logLevels" />
              </label>
              <label v-if="!server" class="field">
                <span>{{ t('settings.mixed_port') }}</span>
                <NInputNumber v-model:value="general.mixed_port" :min="1024" :max="65535" />
              </label>
              <label v-if="!server" class="field row">
                <NCheckbox v-model:checked="general.auto_connect">{{
                  t('settings.auto_connect')
                }}</NCheckbox>
                <NCheckbox v-model:checked="general.auto_reconnect">{{
                  t('settings.auto_reconnect')
                }}</NCheckbox>
              </label>
              <label v-if="server" class="field">
                <span>{{ t('settings.public_base_url') }}</span>
                <NInput
                  v-model:value="general.public_base_url"
                  placeholder="https://vpn.example.com"
                />
                <small class="o-subtle">{{ t('settings.public_base_url_hint') }}</small>
              </label>
              <label v-if="server" class="field">
                <span>{{ t('settings.acme_email') }}</span>
                <NInput v-model:value="general.acme_email" placeholder="admin@example.com" />
              </label>
              <label v-if="server" class="field row">
                <NCheckbox v-model:checked="general.acme_staging">{{
                  t('settings.acme_staging')
                }}</NCheckbox>
                <NCheckbox v-model:checked="general.block_private_egress">{{
                  t('settings.block_private_egress')
                }}</NCheckbox>
              </label>
            </div>
            <template #footer>
              <div class="footer-actions">
                <NButton type="primary" :loading="saving" @click="saveGeneral">
                  <template #icon><Save :size="15" /></template>
                  {{ t('common.save') }}
                </NButton>
              </div>
            </template>
          </OSectionCard>

          <OSectionCard v-if="server" :title="t('settings.public_ui')" :icon="Globe2">
            <div class="public-ui">
              <div class="public-toggle">
                <div>
                  <strong>{{ t('settings.public_ui') }}</strong>
                  <p class="o-small o-muted">{{ t('settings.public_ui_hint') }}</p>
                </div>
                <NSwitch
                  :value="publicUiEnabled"
                  :aria-label="t('settings.public_ui')"
                  @update:value="togglePublicUi"
                />
              </div>
              <label class="field">
                <span>{{ t('certs.domain') }}</span>
                <NSelect
                  v-model:value="publicUiDomain"
                  :options="certDomains"
                  :placeholder="t('setup.domain_placeholder')"
                />
              </label>
              <p v-if="!auth.totpEnabled" class="warning-text">{{ t('auth.totp_hint') }}</p>
            </div>
          </OSectionCard>
        </template>

        <template v-else-if="activeTab === 'security'">
          <OSectionCard :title="t('auth.change_password')" :icon="LockKeyhole">
            <div class="form-grid">
              <label class="field"
                ><span>{{ t('auth.current_password') }}</span
                ><NInput
                  v-model:value="passwordForm.current"
                  type="password"
                  show-password-on="click"
              /></label>
              <label class="field"
                ><span>{{ t('auth.new_password') }}</span
                ><NInput v-model:value="passwordForm.next" type="password" show-password-on="click"
              /></label>
              <label class="field"
                ><span>{{ t('auth.confirm_password') }}</span
                ><NInput
                  v-model:value="passwordForm.confirm"
                  type="password"
                  show-password-on="click"
              /></label>
            </div>
            <template #footer>
              <div class="footer-actions">
                <NButton type="primary" @click="changePassword">{{
                  t('auth.change_password')
                }}</NButton>
              </div>
            </template>
          </OSectionCard>

          <OSectionCard :title="t('auth.totp_enable')" :icon="ShieldCheck">
            <div class="totp-row">
              <div>
                <OStatusPill
                  :status="auth.totpEnabled ? 'enabled' : 'disabled'"
                  :label="auth.totpEnabled ? t('auth.totp_enabled') : t('auth.totp_disable')"
                  size="sm"
                />
                <p class="o-small o-muted">{{ t('auth.totp_scan') }}</p>
              </div>
              <NButton v-if="!auth.totpEnabled" type="primary" @click="startTotp">{{
                t('auth.totp_enable')
              }}</NButton>
              <NButton
                v-else
                secondary
                type="error"
                :loading="disablingTotp"
                @click="disableTotp"
                >{{ t('auth.totp_disable') }}</NButton
              >
            </div>
          </OSectionCard>

          <OSectionCard :title="t('settings.ip_allowlist')" :icon="ShieldCheck">
            <label class="field">
              <span>{{ t('settings.ip_allowlist') }}</span>
              <NInput
                v-model:value="allowlist"
                type="textarea"
                :autosize="{ minRows: 2, maxRows: 4 }"
                placeholder="203.0.113.0/24, 2001:db8::/32"
              />
              <small class="o-subtle">{{ t('settings.ip_allowlist_hint') }}</small>
            </label>
            <template #footer>
              <div class="footer-actions">
                <NButton type="primary" :loading="saving" @click="saveAllowlist">
                  <template #icon><Save :size="15" /></template>
                  {{ t('common.save') }}
                </NButton>
              </div>
            </template>
          </OSectionCard>

          <OSectionCard :title="t('settings.api_tokens')" :icon="KeyRound">
            <template #actions>
              <NButton size="small" type="primary" @click="tokenOpen = true">
                <template #icon><Plus :size="14" /></template>
                {{ t('settings.new_token') }}
              </NButton>
            </template>
            <OEmptyState
              v-if="!apiTokens.length"
              compact
              :title="t('settings.api_tokens')"
              :description="t('settings.new_token')"
            />
            <div v-else class="token-list">
              <div v-for="token in apiTokens" :key="String(token.id)" class="token">
                <div>
                  <strong>{{ token.name }}</strong>
                  <span class="o-micro o-subtle"
                    >{{ (token.scopes as string[]).join(', ') }} ·
                    {{
                      token.last_used_at
                        ? formatDate(String(token.last_used_at), locale)
                        : t('common.never')
                    }}</span
                  >
                </div>
                <NButton size="tiny" quaternary type="error" @click="revokeToken(String(token.id))">
                  <template #icon><Trash2 :size="13" /></template>
                  {{ t('common.revoke') }}
                </NButton>
              </div>
            </div>
          </OSectionCard>
        </template>

        <template v-else-if="activeTab === 'notifications'">
          <OSectionCard :title="t('settings.notifications')" :icon="Bell">
            <div class="form-stack">
              <label class="field">
                <span>{{ t('settings.webhook') }}</span>
                <NInput
                  v-model:value="notifications.webhook_url"
                  placeholder="https://example.com/hook"
                />
              </label>
              <label class="field">
                <span>{{ t('settings.webhook_secret') }}</span>
                <NInput
                  v-model:value="notifications.webhook_secret"
                  type="password"
                  show-password-on="click"
                  :placeholder="settings?.notifications.has_webhook_secret ? '••••••••' : ''"
                />
              </label>
              <NCheckbox
                v-if="settings?.notifications.has_webhook_secret"
                v-model:checked="clearWebhookSecret"
                >{{ t('settings.clear_webhook_secret') }}</NCheckbox
              >
              <NCheckbox v-model:checked="notifications.enabled">{{
                t('settings.notifications_enabled')
              }}</NCheckbox>
              <div class="browser-notify">
                <NButton
                  size="small"
                  secondary
                  :disabled="browserNotifications.granted.value"
                  @click="enableBrowserNotifications"
                >
                  {{ t('notify.enable_browser') }}
                </NButton>
                <span class="o-micro o-subtle">{{ browserNotifications.permission.value }}</span>
              </div>
            </div>
            <template #footer>
              <div class="footer-actions">
                <NButton type="primary" :loading="saving" @click="saveNotifications">{{
                  t('common.save')
                }}</NButton>
              </div>
            </template>
          </OSectionCard>
        </template>

        <template v-else>
          <OSectionCard :title="t('settings.maintenance')" :icon="Database">
            <div class="form-grid">
              <label class="field">
                <span>{{ t('settings.update_channel') }}</span>
                <NSelect
                  v-model:value="maintenance.update_channel"
                  :options="[
                    { label: t('settings.update_channel_stable'), value: 'stable' },
                    { label: t('settings.update_channel_beta'), value: 'beta' },
                  ]"
                />
              </label>
              <label class="field">
                <span>{{ t('settings.audit_retention') }}</span>
                <NInputNumber
                  v-model:value="maintenance.audit_retention_days"
                  :min="7"
                  :max="3650"
                />
              </label>
              <label class="field">
                <span>{{ t('settings.traffic_retention') }}</span>
                <NInputNumber
                  v-model:value="maintenance.traffic_retention_days"
                  :min="30"
                  :max="3650"
                />
              </label>
              <label class="field">
                <span>{{ t('settings.job_retention') }}</span>
                <NInputNumber v-model:value="maintenance.job_retention_days" :min="1" :max="365" />
              </label>
              <label class="field row">
                <NCheckbox v-model:checked="maintenance.auto_backup">{{
                  t('settings.auto_backup')
                }}</NCheckbox>
              </label>
            </div>
            <template #footer>
              <div class="footer-actions">
                <NButton type="primary" :loading="saving" @click="saveMaintenance">{{
                  t('common.save')
                }}</NButton>
              </div>
            </template>
          </OSectionCard>

          <OSectionCard :title="t('settings.backups')" :icon="Database">
            <template #actions>
              <NButton size="small" type="primary" @click="backupOpen = true">
                <template #icon><Plus :size="14" /></template>
                {{ t('common.create') }}
              </NButton>
            </template>
            <OEmptyState
              v-if="!backups.length"
              compact
              :title="t('common.no_data')"
              :description="t('settings.auto_backup')"
            />
            <div v-else class="backup-list">
              <div v-for="backup in backups" :key="backup.id" class="backup">
                <div class="backup-copy">
                  <strong class="o-truncate">{{ backup.filename }}</strong>
                  <span class="o-micro o-subtle"
                    >{{ formatBytes(backup.size) }} · {{ formatDate(backup.created_at, locale) }} ·
                    {{
                      backup.encrypted ? t('settings.backup_encrypted') : t('settings.backup_plain')
                    }}</span
                  >
                </div>
                <NButton size="tiny" secondary @click="restore(backup)">{{
                  t('common.apply')
                }}</NButton>
                <NButton
                  size="tiny"
                  quaternary
                  type="error"
                  :aria-label="t('common.delete')"
                  @click="removeBackup(backup)"
                >
                  <template #icon><Trash2 :size="13" /></template>
                </NButton>
              </div>
            </div>
          </OSectionCard>
        </template>
      </div>
    </div>

    <NModal
      v-model:show="tokenOpen"
      preset="card"
      :style="{ width: 'min(480px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('settings.new_token') }}</template>
      <div class="form-stack">
        <label class="field"
          ><span>{{ t('settings.token_name') }}</span
          ><NInput v-model:value="tokenName" placeholder="ci-deploy"
        /></label>
        <label class="field"
          ><span>{{ t('settings.token_scopes') }}</span>
          <NCheckboxGroup v-model:value="tokenScopes">
            <NCheckbox value="read" label="read" />
            <NCheckbox value="write" label="write" />
          </NCheckboxGroup>
        </label>
      </div>
      <template #footer>
        <div class="footer-actions">
          <NButton secondary @click="tokenOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" @click="createToken">{{ t('common.create') }}</NButton>
        </div>
      </template>
    </NModal>

    <NModal
      :show="!!newToken"
      preset="card"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }"
      :bordered="false"
      @update:show="newToken = null"
    >
      <template #header>{{ t('settings.token_created') }}</template>
      <p class="o-muted o-small">{{ t('settings.token_once') }}</p>
      <div class="token-once">
        <code>{{ newToken }}</code>
        <OCopyButton v-if="newToken" :value="newToken" />
      </div>
    </NModal>

    <NModal
      v-model:show="totpModal"
      preset="card"
      :style="{ width: 'min(520px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('auth.totp_enable') }}</template>
      <div v-if="totpStart" class="totp-start">
        <div class="totp-qr" @click="showQr(totpStart.uri)">
          <QrcodeVue
            :value="totpStart.uri"
            :size="160"
            level="M"
            foreground="#0b1220"
            background="#ffffff"
          />
        </div>
        <p class="o-small o-muted">{{ t('auth.totp_scan') }}</p>
        <div class="secret-row">
          <span>{{ t('auth.totp') }}</span><code>{{ totpStart.secret }}</code
          ><OCopyButton :value="totpStart.secret" size="tiny" />
        </div>
        <div class="recovery">
          <p class="o-micro o-subtle">{{ t('auth.recovery_codes') }}</p>
          <div class="codes">
            <code v-for="code in totpStart.recovery_codes" :key="code">{{ code }}</code>
          </div>
          <p class="o-micro o-subtle">{{ t('auth.recovery_hint') }}</p>
        </div>
        <label class="field"
          ><span>{{ t('auth.totp') }}</span
          ><NInput v-model:value="totpCode" maxlength="8" placeholder="123456"
        /></label>
      </div>
      <template #footer>
        <div class="footer-actions">
          <NButton secondary @click="cancelTotp">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" @click="confirmTotp">{{ t('common.confirm') }}</NButton>
        </div>
      </template>
    </NModal>

    <NModal
      v-model:show="disableTotpOpen"
      preset="card"
      :style="{ width: 'min(460px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('auth.totp_disable') }}</template>
      <label class="field"
        ><span>{{ t('auth.password') }}</span
        ><NInput
          v-model:value="disableTotpPassword"
          type="password"
          show-password-on="click"
          @keyup.enter="confirmDisableTotp"
      /></label>
      <template #footer>
        <div class="footer-actions">
          <NButton secondary @click="disableTotpOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton
            type="error"
            :loading="disablingTotp"
            :disabled="!disableTotpPassword"
            @click="confirmDisableTotp"
            >{{ t('auth.totp_disable') }}</NButton
          >
        </div>
      </template>
    </NModal>

    <NModal
      v-model:show="backupOpen"
      preset="card"
      :style="{ width: 'min(480px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('common.create') }}</template>
      <div class="form-stack">
        <p class="warning-text">{{ t('settings.backup_plaintext_warning') }}</p>
        <label class="field"
          ><span>{{ t('settings.backup_password') }}</span
          ><NInput
            v-model:value="backupPassword"
            type="password"
            show-password-on="click"
            :placeholder="t('common.optional')"
        /></label>
        <NCheckbox v-if="!backupPassword" v-model:checked="backupAck">{{
          t('settings.backup_plaintext_ack')
        }}</NCheckbox>
      </div>
      <template #footer>
        <div class="footer-actions">
          <NButton secondary @click="backupOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :disabled="!backupPassword && !backupAck" @click="createBackup">{{
            t('common.create')
          }}</NButton>
        </div>
      </template>
    </NModal>

    <NModal
      v-model:show="restoreOpen"
      preset="card"
      :style="{ width: 'min(480px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('common.apply') }}</template>
      <p class="o-small o-muted">{{ restoring?.filename }}</p>
      <label v-if="restoring?.encrypted" class="field"
        ><span>{{ t('settings.backup_password') }}</span
        ><NInput v-model:value="restorePassword" type="password" show-password-on="click"
      /></label>
      <template #footer>
        <div class="footer-actions">
          <NButton secondary @click="restoreOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" @click="confirmRestore">{{ t('common.apply') }}</NButton>
        </div>
      </template>
    </NModal>

    <OQrModal v-model:show="qrOpen" :value="qrValue" :title="t('auth.totp_enable')" />
  </div>
</template>

<style scoped>
.settings-layout {
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
.settings-nav {
  padding: 8px;
  position: sticky;
  top: calc(var(--topbar-height) + 20px);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.settings-nav button {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 11px;
  border-radius: 9px;
  border: 0;
  background: transparent;
  color: var(--text-2);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.settings-nav button:hover {
  background: var(--surface-2);
  color: var(--text);
}
.settings-nav button.active {
  background: var(--accent-soft);
  color: var(--accent);
}
.settings-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.form-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
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
.field.row {
  justify-content: flex-end;
}
.field small {
  line-height: 1.5;
}
.segmented {
  display: inline-flex;
  padding: 3px;
  border-radius: 9px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  gap: 2px;
  width: fit-content;
}
.segmented button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 9px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-2);
  font-size: 10.5px;
  cursor: pointer;
}
.segmented button.active {
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow-1);
}
.footer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.public-ui {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.public-toggle {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}
.public-toggle strong {
  display: block;
  font-size: 12.5px;
}
.warning-text {
  color: var(--warning);
  font-size: 11px;
}
.browser-notify {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.totp-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.totp-row p {
  margin-top: 4px;
}
.token-list,
.backup-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.token,
.backup {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}
.token:last-child,
.backup:last-child {
  border-bottom: 0;
}
.token > div,
.backup-copy {
  flex: 1;
  min-width: 0;
}
.token strong,
.backup-copy strong {
  display: block;
  font-size: 11.5px;
  font-weight: 600;
}
.token-once {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border-radius: 9px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.token-once code {
  flex: 1;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  word-break: break-all;
}
.totp-start {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.totp-qr {
  align-self: center;
  padding: 10px;
  background: #fff;
  border-radius: 12px;
  cursor: pointer;
}
.secret-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.secret-row span {
  color: var(--text-3);
  font-size: 10px;
}
.secret-row code {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 11px;
}
.recovery {
  padding: 10px;
  border-radius: 9px;
  background: var(--warning-soft);
}
.codes {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  margin: 6px 0;
}
.codes code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--warning);
}
@media (max-width: 1000px) {
  .settings-layout {
    grid-template-columns: 1fr;
  }
  .settings-nav {
    position: static;
    flex-direction: row;
    overflow-x: auto;
  }
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
