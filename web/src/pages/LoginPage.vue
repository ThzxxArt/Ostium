<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton, NForm, NFormItem, NInput, useMessage } from 'naive-ui'
import {
  ArrowRight,
  Languages,
  LockKeyhole,
  Moon,
  ShieldCheck,
  Sun,
  UserRound,
  Waypoints,
} from 'lucide-vue-next'
import OBrandMark from '@/components/OBrandMark.vue'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { ApiError } from '@/api/client'

const auth = useAuthStore()
const app = useAppStore()
const router = useRouter()
const route = useRoute()
const message = useMessage()
const { t } = useI18n()

const username = ref('')
const password = ref('')
const totp = ref('')
const needsTotp = ref(false)
const loading = ref(false)
const error = ref<string | null>(null)
const version = computed(() => auth.status?.version || '0.1.0')

onMounted(async () => {
  if (!auth.ready) await auth.bootstrap()
})

async function submit() {
  if (!username.value || !password.value) {
    error.value = t('auth.invalid')
    return
  }
  loading.value = true
  error.value = null
  try {
    await auth.login(username.value, password.value, needsTotp.value ? totp.value : undefined)
    const next = typeof route.query.next === 'string' ? route.query.next : '/'
    await router.replace(next)
  } catch (err) {
    if (err instanceof ApiError && err.code === 'totp_required') {
      needsTotp.value = true
      error.value = t('auth.totp_hint')
    } else if (err instanceof ApiError && err.code === 'rate_limited') {
      error.value = t('auth.invalid')
    } else {
      error.value = err instanceof Error ? err.message : t('errors.unknown')
    }
    message.error(error.value)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <section class="visual" aria-hidden="true">
      <div class="aurora a" />
      <div class="aurora b" />
      <div class="grid" />
      <div class="visual-inner">
        <div class="brand-row">
          <OBrandMark :size="40" />
          <span class="edition">PRIVATE NETWORK</span>
        </div>
        <h1>One quiet place<br />for your whole network.</h1>
        <p class="lead">
          Reality, Hysteria2, TUN and per-user control — designed to stay out of your way.
        </p>
        <ul class="features">
          <li>
            <span class="ico"><Waypoints :size="17" /></span>
            <div>
              <strong>Four mature protocols</strong
              ><span>Reality, Hysteria2, Trojan and SS2022 in one console.</span>
            </div>
          </li>
          <li>
            <span class="ico"><ShieldCheck :size="17" /></span>
            <div>
              <strong>Private by default</strong
              ><span>Loopback admin, no telemetry, encrypted secrets.</span>
            </div>
          </li>
          <li>
            <span class="ico"><LockKeyhole :size="17" /></span>
            <div>
              <strong>Two-service isolation</strong
              ><span>The UI never runs with network privileges.</span>
            </div>
          </li>
        </ul>
        <div class="visual-foot">
          <span>Ostium {{ version }}</span>
          <span class="sep">·</span>
          <span>GPL-3.0-or-later</span>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-top">
        <div class="mobile-brand"><OBrandMark :size="30" /></div>
        <div class="panel-tools">
          <button
            type="button"
            class="tool"
            :aria-label="t('settings.language')"
            @click="app.toggleLanguage()"
          >
            <Languages :size="16" />
            <span>{{ app.locale.startsWith('zh') ? 'EN' : '中' }}</span>
          </button>
          <button
            type="button"
            class="tool"
            :aria-label="t('settings.theme')"
            @click="app.toggleTheme()"
          >
            <component :is="app.isDark ? Sun : Moon" :size="16" />
          </button>
        </div>
      </div>

      <div class="form-wrap">
        <div class="heading">
          <p class="o-kicker">{{ t('app.name') }}</p>
          <h2>{{ t('auth.welcome_back') }}</h2>
          <p class="o-muted">{{ t('auth.login_subtitle') }}</p>
        </div>

        <NForm class="form" @submit.prevent="submit">
          <NFormItem :label="t('auth.username')" :show-feedback="false">
            <NInput
              v-model:value="username"
              size="large"
              autocomplete="username"
              :placeholder="t('auth.username')"
            >
              <template #prefix><UserRound :size="16" /></template>
            </NInput>
          </NFormItem>
          <NFormItem :label="t('auth.password')" :show-feedback="false">
            <NInput
              v-model:value="password"
              type="password"
              show-password-on="click"
              size="large"
              autocomplete="current-password"
              :placeholder="t('auth.password')"
              @keyup.enter="submit"
            >
              <template #prefix><LockKeyhole :size="16" /></template>
            </NInput>
          </NFormItem>
          <NFormItem v-if="needsTotp" :label="t('auth.totp')" :show-feedback="false">
            <NInput
              v-model:value="totp"
              size="large"
              maxlength="8"
              autocomplete="one-time-code"
              placeholder="123456"
            />
          </NFormItem>
          <p v-if="error" class="error" role="alert">{{ error }}</p>
          <NButton
            type="primary"
            size="large"
            block
            :loading="loading"
            attr-type="submit"
            class="submit"
          >
            {{ t('auth.sign_in') }}
            <template #icon><ArrowRight :size="17" /></template>
          </NButton>
        </NForm>

        <div class="footnote">
          <span class="dot" />
          <span>{{ t('auth.login_subtitle') }}</span>
        </div>
      </div>

      <div class="panel-foot">
        <span>{{ t('footer.privacy') }}</span>
        <a href="https://github.com/ThzxxArt/Ostium" target="_blank" rel="noopener">GitHub</a>
      </div>
    </section>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(420px, 0.85fr);
}
.visual {
  position: relative;
  overflow: hidden;
  border-right: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 64px clamp(40px, 6vw, 96px);
  background:
    radial-gradient(700px 500px at 18% 18%, rgba(45, 212, 191, 0.16), transparent 62%),
    radial-gradient(600px 460px at 82% 72%, rgba(96, 165, 250, 0.15), transparent 60%), var(--bg);
}
.aurora {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.55;
}
.aurora.a {
  width: 480px;
  height: 480px;
  background: rgba(45, 212, 191, 0.18);
  top: -120px;
  right: -80px;
}
.aurora.b {
  width: 420px;
  height: 420px;
  background: rgba(96, 165, 250, 0.18);
  bottom: -160px;
  left: 10%;
}
.grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.05) 1px, transparent 1px);
  background-size: 56px 56px;
  mask-image: radial-gradient(circle at 50% 40%, #000 20%, transparent 78%);
}
.visual-inner {
  position: relative;
  z-index: 1;
  max-width: 560px;
}
.brand-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 42px;
}
.edition {
  font-size: 9.5px;
  letter-spacing: 0.24em;
  color: var(--text-3);
}
h1 {
  font-size: clamp(34px, 4.2vw, 54px);
  line-height: 1.12;
  letter-spacing: -0.04em;
  font-weight: 600;
}
.lead {
  margin-top: 18px;
  max-width: 460px;
  color: var(--text-2);
  font-size: 14.5px;
  line-height: 1.7;
}
.features {
  list-style: none;
  padding: 0;
  margin: 42px 0 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.features li {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.ico {
  width: 36px;
  height: 36px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
}
.features strong {
  display: block;
  font-size: 13px;
  font-weight: 600;
}
.features span {
  color: var(--text-2);
  font-size: 12px;
}
.visual-foot {
  margin-top: 56px;
  display: flex;
  gap: 8px;
  color: var(--text-3);
  font-size: 10.5px;
}
.panel {
  display: flex;
  flex-direction: column;
  padding: 28px 36px 24px;
  background: color-mix(in srgb, var(--bg) 65%, var(--surface) 35%);
}
.panel-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mobile-brand {
  display: none;
}
.panel-tools {
  display: flex;
  gap: 6px;
  margin-left: auto;
}
.tool {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 9px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  font-size: 10.5px;
}
.tool:hover {
  color: var(--text);
  border-color: var(--border-strong);
}
.form-wrap {
  margin: auto;
  width: 100%;
  max-width: 380px;
  padding: 40px 0;
}
.heading h2 {
  font-size: 26px;
  letter-spacing: -0.03em;
  font-weight: 600;
  margin-top: 8px;
}
.heading p {
  margin-top: 6px;
  font-size: 13px;
}
.form {
  margin-top: 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.form :deep(.n-form-item-label) {
  font-size: 12px;
  color: var(--text-2);
  padding-bottom: 6px;
}
.error {
  color: var(--danger);
  font-size: 12px;
  background: var(--danger-soft);
  border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
  border-radius: 9px;
  padding: 8px 10px;
}
.submit {
  margin-top: 4px;
  height: 46px;
  font-weight: 600;
}
.footnote {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 22px;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.5;
}
.dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--success);
  margin-top: 4px;
  flex: none;
}
.panel-foot {
  display: flex;
  justify-content: space-between;
  color: var(--text-3);
  font-size: 10px;
}
.panel-foot a {
  color: var(--text-3);
}
@media (max-width: 1023px) {
  .auth-page {
    grid-template-columns: 1fr;
  }
  .visual {
    display: none;
  }
  .mobile-brand {
    display: block;
  }
  .panel {
    min-height: 100vh;
    padding: 24px 22px;
  }
}
</style>
