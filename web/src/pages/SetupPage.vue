<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton, NCheckbox, NInput, useMessage } from 'naive-ui'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Globe2,
  Laptop,
  Server,
  ShieldCheck,
  Sparkles,
  Waypoints,
} from '@lucide/vue'
import OBrandMark from '@/components/OBrandMark.vue'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { api } from '@/api'

const auth = useAuthStore()
const app = useAppStore()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()

const role = computed(() => auth.role)
const steps = computed(() =>
  role.value === 'server'
    ? [
        t('setup.step_account'),
        t('setup.step_role'),
        t('setup.step_transport'),
        t('setup.step_review'),
      ]
    : [t('setup.step_account'), t('setup.step_import'), t('setup.step_mode')],
)
const step = ref(0)
const loading = ref(false)
const error = ref<string | null>(null)

const username = ref('admin')
const password = ref('')
const confirm = ref('')
const domain = ref('')
const transport = ref<'reality' | 'later'>('reality')
const importText = ref('')
const clientMode = ref<'mixed' | 'system_proxy' | 'tun'>('system_proxy')
const accepted = ref(false)

const canNext = computed(() => {
  if (step.value === 0) {
    return (
      username.value.trim().length > 0 &&
      password.value.length >= 10 &&
      password.value === confirm.value
    )
  }
  if (step.value === 1 && role.value === 'server') return true
  if (step.value === steps.value.length - 1) return accepted.value || role.value === 'client'
  return true
})

function back() {
  if (step.value > 0) step.value -= 1
}

async function next() {
  if (!canNext.value) {
    if (step.value === 0 && password.value !== confirm.value)
      error.value = t('auth.password_mismatch')
    else if (step.value === 0) error.value = t('auth.password_too_short')
    return
  }
  error.value = null
  if (step.value < steps.value.length - 1) {
    step.value += 1
    return
  }
  await finish()
}

async function finish() {
  loading.value = true
  error.value = null
  try {
    await auth.setup({
      role: role.value,
      username: username.value.trim(),
      password: password.value,
      domain: domain.value.trim() || undefined,
      lines: role.value === 'server' ? transport.value : undefined,
    })
    if (role.value === 'client') {
      const importValue = importText.value.trim()
      if (importValue) {
        try {
          // The wizard accepts both a subscription URL and pasted links/JSON.
          // Sending a URL through the text parser makes Endpoint.from_uri()
          // reject the https:// scheme and silently leaves the client without
          // a profile.
          if (/^https?:\/\//i.test(importValue)) {
            await api.profiles.create({ name: 'Imported', url: importValue })
          } else {
            await api.profiles.create({ name: 'Imported', text: importValue })
          }
        } catch (err) {
          message.warning((err as Error).message)
        }
      }
      try {
        await api.system.mode(clientMode.value)
      } catch {
        /* core may not be running yet */
      }
      await router.replace('/onboarding')
    } else {
      await router.replace('/')
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('errors.unknown')
  } finally {
    loading.value = false
  }
}

const transportOptions = computed(() => [
  {
    id: 'reality' as const,
    title: t('setup.reality'),
    description: t('setup.reality_desc'),
    icon: ShieldCheck,
    badge: 'Recommended',
  },
  {
    id: 'later' as const,
    title: t('setup.configure_later'),
    description: t('setup.configure_later_desc'),
    icon: Waypoints,
    badge: t('setup.later_badge'),
  },
])
</script>

<template>
  <div class="setup-page">
    <header class="top">
      <OBrandMark :size="32" />
      <div class="tools">
        <button type="button" class="tool" @click="app.toggleLanguage()">
          {{ app.locale.startsWith('zh') ? 'EN' : '中' }}
        </button>
        <button type="button" class="tool" @click="app.toggleTheme()">
          <component :is="app.isDark ? Sparkles : Sparkles" :size="15" />
        </button>
      </div>
    </header>

    <main class="wrap">
      <aside class="intro">
        <p class="o-kicker">{{ t('setup.title') }}</p>
        <h1>{{ t('app.tagline') }}</h1>
        <p class="lead">{{ t('setup.subtitle') }}</p>
        <div class="role-card">
          <span class="role-icon"
            ><component :is="role === 'server' ? Server : Laptop" :size="19"
          /></span>
          <div>
            <strong>{{ role === 'server' ? t('setup.server') : t('setup.client') }}</strong>
            <span>{{ role === 'server' ? t('setup.server_desc') : t('setup.client_desc') }}</span>
          </div>
        </div>
        <ol class="step-list">
          <li
            v-for="(label, index) in steps"
            :key="label"
            :class="{ active: index === step, done: index < step }"
          >
            <span class="step-dot">
              <Check v-if="index < step" :size="12" />
              <template v-else>{{ index + 1 }}</template>
            </span>
            <span>{{ label }}</span>
          </li>
        </ol>
        <p class="role-hint">{{ t('setup.role_hint') }}</p>
      </aside>

      <section class="card">
        <div class="card-head">
          <p class="o-micro o-subtle">
            {{ String(step + 1).padStart(2, '0') }} / {{ String(steps.length).padStart(2, '0') }}
          </p>
          <h2>{{ steps[step] }}</h2>
        </div>

        <div v-if="step === 0" class="form">
          <label class="field">
            <span>{{ t('setup.username') }}</span>
            <NInput v-model:value="username" size="large" autocomplete="username" />
          </label>
          <label class="field">
            <span>{{ t('setup.password') }}</span>
            <NInput
              v-model:value="password"
              type="password"
              show-password-on="click"
              size="large"
              autocomplete="new-password"
            />
            <small class="o-subtle">{{ t('setup.password_hint') }}</small>
          </label>
          <label class="field">
            <span>{{ t('auth.confirm_password') }}</span>
            <NInput
              v-model:value="confirm"
              type="password"
              show-password-on="click"
              size="large"
              autocomplete="new-password"
            />
          </label>
        </div>

        <div v-else-if="step === 1 && role === 'server'" class="form">
          <div class="role-note">
            <span class="role-icon"><Globe2 :size="19" /></span>
            <div>
              <strong>{{ t('setup.server') }}</strong><span>{{ t('setup.server_desc') }}</span>
            </div>
          </div>
          <label class="field">
            <span
              >{{ t('setup.domain') }} <em>{{ t('common.optional') }}</em></span
            >
            <NInput
              v-model:value="domain"
              size="large"
              :placeholder="t('setup.domain_placeholder')"
            />
            <small class="o-subtle">{{ t('setup.domain_hint') }}</small>
          </label>
        </div>

        <div v-else-if="step === 1 && role === 'client'" class="form">
          <label class="field">
            <span>{{ t('setup.client_import_hint') }}</span>
            <NInput
              v-model:value="importText"
              type="textarea"
              :autosize="{ minRows: 5, maxRows: 10 }"
              :placeholder="t('profiles.url_hint')"
            />
            <small class="o-subtle">{{ t('setup.client_import_hint') }}</small>
          </label>
        </div>

        <div v-else-if="step === 2 && role === 'server'" class="transport">
          <button
            v-for="option in transportOptions"
            :key="option.id"
            type="button"
            class="transport-card"
            :class="{ active: transport === option.id }"
            @click="transport = option.id"
          >
            <span class="transport-icon"><component :is="option.icon" :size="21" /></span>
            <span class="transport-copy">
              <strong>{{ option.title }}</strong>
              <span>{{ option.description }}</span>
            </span>
            <span class="transport-badge">{{ option.badge }}</span>
            <span v-if="transport === option.id" class="check"><Check :size="13" /></span>
          </button>
          <p v-if="transport !== 'reality'" class="hint">
            {{ t('setup.later_hint') }}
          </p>
        </div>

        <div v-else-if="step === 2 && role === 'client'" class="transport">
          <button
            v-for="option in [
              {
                id: 'mixed' as const,
                title: t('network.mixed'),
                desc: t('network.mixed_desc'),
                icon: Waypoints,
              },
              {
                id: 'system_proxy' as const,
                title: t('network.system'),
                desc: t('network.system_desc'),
                icon: Globe2,
              },
              {
                id: 'tun' as const,
                title: t('network.tun'),
                desc: t('network.tun_desc'),
                icon: ShieldCheck,
              },
            ]"
            :key="option.id"
            type="button"
            class="transport-card"
            :class="{ active: clientMode === option.id }"
            @click="clientMode = option.id"
          >
            <span class="transport-icon"><component :is="option.icon" :size="21" /></span>
            <span class="transport-copy">
              <strong>{{ option.title }}</strong>
              <span>{{ option.desc }}</span>
            </span>
            <span v-if="clientMode === option.id" class="check"><Check :size="13" /></span>
          </button>
          <p class="hint">{{ t('setup.client_mode_hint') }}</p>
        </div>

        <div v-else class="review">
          <div class="review-row">
            <span>{{ t('setup.username') }}</span><strong>{{ username }}</strong>
          </div>
          <div class="review-row">
            <span>{{ t('setup.step_role') }}</span><strong>{{
              role === 'server' ? t('setup.server') : t('setup.client')
            }}</strong>
          </div>
          <div v-if="role === 'server'" class="review-row">
            <span>{{ t('setup.domain') }}</span><strong>{{ domain || '—' }}</strong>
          </div>
          <div v-if="role === 'server'" class="review-row">
            <span>{{ t('setup.step_transport') }}</span><strong>{{ transport }}</strong>
          </div>
          <div v-else class="review-row">
            <span>{{ t('network.current') }}</span><strong>{{ clientMode }}</strong>
          </div>
          <NCheckbox v-model:checked="accepted">
            <span class="o-small">{{ t('setup.review_hint') }}</span>
          </NCheckbox>
          <p class="o-subtle o-micro">{{ t('setup.public_ui_hint') }}</p>
        </div>

        <p v-if="error" class="error" role="alert">{{ error }}</p>

        <footer class="card-actions">
          <NButton v-if="step > 0" secondary size="large" @click="back">
            <template #icon><ArrowLeft :size="16" /></template>
            {{ t('common.previous') }}
          </NButton>
          <div class="spacer" />
          <NButton
            type="primary"
            size="large"
            :loading="loading"
            :disabled="!canNext"
            @click="next"
          >
            {{
              step === steps.length - 1
                ? role === 'server'
                  ? t('setup.create')
                  : t('setup.finish_client')
                : t('common.next')
            }}
            <template #icon><ArrowRight :size="16" /></template>
          </NButton>
        </footer>
      </section>
    </main>
  </div>
</template>

<style scoped>
.setup-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.top {
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 clamp(20px, 5vw, 56px);
}
.tools {
  display: flex;
  gap: 8px;
}
.tool {
  height: 32px;
  min-width: 32px;
  padding: 0 9px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  font-size: 10.5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.wrap {
  flex: 1;
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  padding: 24px clamp(20px, 5vw, 56px) 64px;
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(420px, 1.1fr);
  gap: clamp(32px, 6vw, 84px);
  align-items: start;
}
.intro {
  padding-top: 28px;
}
h1 {
  margin-top: 10px;
  font-size: clamp(34px, 4vw, 50px);
  line-height: 1.1;
  letter-spacing: -0.04em;
  font-weight: 600;
}
.lead {
  margin-top: 16px;
  max-width: 420px;
  color: var(--text-2);
  line-height: 1.7;
  font-size: 14px;
}
.role-card {
  margin-top: 28px;
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--surface);
  max-width: 420px;
}
.role-icon {
  width: 36px;
  height: 36px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: var(--accent);
  background: var(--accent-soft);
}
.role-card strong,
.role-note strong {
  display: block;
  font-size: 13px;
}
.role-card span,
.role-note span {
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.5;
}
.step-list {
  list-style: none;
  padding: 0;
  margin: 32px 0 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.step-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-3);
  font-size: 12.5px;
}
.step-list li.active {
  color: var(--text);
}
.step-list li.done {
  color: var(--text-2);
}
.step-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  border: 1px solid var(--border);
  font-size: 10px;
  font-weight: 600;
}
.active .step-dot {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: var(--accent-soft);
}
.done .step-dot {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 35%, transparent);
}
.role-hint {
  margin-top: 32px;
  max-width: 380px;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.6;
}
.card {
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  box-shadow: var(--shadow-2);
  padding: 28px;
  min-height: 480px;
  display: flex;
  flex-direction: column;
}
.card-head h2 {
  margin-top: 4px;
  font-size: 21px;
  letter-spacing: -0.02em;
  font-weight: 600;
}
.form {
  margin-top: 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.field > span {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
}
.field em {
  font-style: normal;
  color: var(--text-3);
  font-size: 10px;
  margin-left: 4px;
}
.field small {
  line-height: 1.5;
}
.transport {
  margin-top: 22px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.transport-card {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  padding: 15px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  text-align: left;
  cursor: pointer;
  color: var(--text);
  transition:
    border-color var(--dur) var(--ease),
    background var(--dur) var(--ease);
}
.transport-card:hover {
  border-color: var(--border-strong);
}
.transport-card.active {
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: var(--accent-soft);
}
.transport-icon {
  width: 38px;
  height: 38px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 11px;
  background: var(--surface);
  color: var(--accent);
  border: 1px solid var(--border);
}
.transport-copy {
  flex: 1;
  min-width: 0;
}
.transport-copy strong {
  display: block;
  font-size: 13px;
  font-weight: 600;
}
.transport-copy span {
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.5;
}
.transport-badge {
  font-size: 9px;
  color: var(--text-3);
  border: 1px solid var(--border);
  padding: 2px 6px;
  border-radius: 6px;
  white-space: nowrap;
}
.check {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: var(--accent);
  background: var(--surface);
  flex: none;
}
.hint {
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.6;
  margin-top: 4px;
}
.role-note {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px;
  border-radius: 14px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.review {
  margin-top: 22px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.review-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
}
.review-row span {
  color: var(--text-2);
}
.error {
  margin-top: 16px;
  color: var(--danger);
  background: var(--danger-soft);
  border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
  border-radius: 9px;
  padding: 8px 10px;
  font-size: 12px;
}
.card-actions {
  margin-top: auto;
  padding-top: 24px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.spacer {
  flex: 1;
}
@media (max-width: 900px) {
  .wrap {
    grid-template-columns: 1fr;
  }
  .intro {
    padding-top: 0;
  }
  .step-list {
    flex-direction: row;
    flex-wrap: wrap;
    gap: 8px 16px;
  }
  .role-hint {
    display: none;
  }
  .card {
    min-height: 0;
  }
}
</style>
