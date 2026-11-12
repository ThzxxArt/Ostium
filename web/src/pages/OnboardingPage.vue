<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, NRadioGroup, NRadio, useMessage } from 'naive-ui'
import { ArrowLeft, ArrowRight, Check, Link2, ShieldCheck, Waypoints } from 'lucide-vue-next'
import OBrandMark from '@/components/OBrandMark.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import { api } from '@/api'
import type { Profile } from '@/api/types'

const { t } = useI18n()
const router = useRouter()
const message = useMessage()

const step = ref(0)
const importMode = ref<'url' | 'text'>('url')
const importUrl = ref('')
const importText = ref('')
const profile = ref<Profile | null>(null)
const loading = ref(false)
const testing = ref(false)
const testResults = ref<
  Array<{ tag: string; name: string; delay_ms: number | null; error: string | null }>
>([])
const mode = ref<'system_proxy' | 'tun' | 'mixed'>('system_proxy')

const steps = computed(() => [
  t('onboarding.step_import'),
  t('onboarding.step_test'),
  t('onboarding.step_mode'),
])
const canImport = computed(() =>
  importMode.value === 'url'
    ? importUrl.value.trim().length > 0
    : importText.value.trim().length > 0,
)

async function importProfile() {
  if (!canImport.value) return
  loading.value = true
  try {
    const result = await api.profiles.create({
      name: 'My server',
      url: importMode.value === 'url' ? importUrl.value.trim() : undefined,
      text: importMode.value === 'text' ? importText.value.trim() : undefined,
    })
    profile.value = result.profile
    step.value = 1
    await testProfile()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function testProfile() {
  if (!profile.value) return
  testing.value = true
  try {
    const result = await api.profiles.test(profile.value.id)
    testResults.value = result.results
  } catch {
    testResults.value = []
  } finally {
    testing.value = false
  }
}

async function finish() {
  loading.value = true
  try {
    await api.system.mode(mode.value)
    await api.system.connect()
    message.success(t('home.connected'))
    await router.replace('/')
  } catch (err) {
    message.warning((err as Error).message)
    await router.replace('/')
  } finally {
    loading.value = false
  }
}

function skip() {
  void router.push('/')
}
</script>

<template>
  <div class="onboarding">
    <header class="top">
      <OBrandMark :size="32" />
      <span class="o-micro o-subtle">Ostium</span>
    </header>

    <main class="card">
      <div class="head">
        <p class="o-kicker">{{ t('onboarding.title') }}</p>
        <h1>{{ t('onboarding.subtitle') }}</h1>
        <div class="steps">
          <div
            v-for="(label, index) in steps"
            :key="label"
            class="step"
            :class="{ active: index === step, done: index < step }"
          >
            <span class="dot"
              ><Check v-if="index < step" :size="10" /><template v-else>{{
                index + 1
              }}</template></span
            >
            <span>{{ label }}</span>
          </div>
        </div>
      </div>

      <section v-if="step === 0" class="body">
        <p class="o-muted o-small">{{ t('onboarding.import_hint') }}</p>
        <NRadioGroup v-model:value="importMode" class="modes">
          <NRadio value="url">{{ t('profiles.import_url') }}</NRadio>
          <NRadio value="text">{{ t('profiles.import_text') }}</NRadio>
        </NRadioGroup>
        <NInput
          v-if="importMode === 'url'"
          v-model:value="importUrl"
          size="large"
          placeholder="https://example.com/sub/token"
        >
          <template #prefix><Link2 :size="16" /></template>
        </NInput>
        <NInput
          v-else
          v-model:value="importText"
          type="textarea"
          :autosize="{ minRows: 6, maxRows: 12 }"
          placeholder="vless://…"
        />
        <div class="actions">
          <NButton secondary @click="skip">{{ t('common.skip') }}</NButton>
          <NButton
            type="primary"
            size="large"
            :disabled="!canImport"
            :loading="loading"
            @click="importProfile"
          >
            {{ t('common.next') }}
            <template #icon><ArrowRight :size="16" /></template>
          </NButton>
        </div>
      </section>

      <section v-else-if="step === 1" class="body">
        <p class="o-muted o-small">{{ t('onboarding.test_hint') }}</p>
        <div class="test-list">
          <div v-for="result in testResults" :key="result.tag" class="test-item">
            <span class="test-icon"><ShieldCheck :size="16" /></span>
            <div class="test-copy">
              <strong>{{ result.name }}</strong>
              <span class="o-micro o-subtle">{{
                result.error || (result.delay_ms ? `${result.delay_ms} ms` : t('common.test'))
              }}</span>
            </div>
            <OStatusPill
              :status="result.error ? 'warning' : result.delay_ms ? 'connected' : 'pending'"
              size="sm"
            />
          </div>
          <p v-if="!testResults.length && !testing" class="o-small o-subtle">
            {{ t('onboarding.no_endpoints') }}
          </p>
        </div>
        <div class="actions">
          <NButton secondary @click="step = 0">
            <template #icon><ArrowLeft :size="16" /></template>
            {{ t('common.back') }}
          </NButton>
          <div class="spacer" />
          <NButton secondary :loading="testing" @click="testProfile">{{
            t('onboarding.skip_test')
          }}</NButton>
          <NButton type="primary" size="large" @click="step = 2">
            {{ t('common.next') }}
            <template #icon><ArrowRight :size="16" /></template>
          </NButton>
        </div>
      </section>

      <section v-else class="body">
        <p class="o-muted o-small">{{ t('onboarding.mode_hint') }}</p>
        <div class="mode-list">
          <button
            type="button"
            class="mode"
            :class="{ active: mode === 'system_proxy' }"
            @click="mode = 'system_proxy'"
          >
            <span class="mode-icon"><ShieldCheck :size="19" /></span>
            <span
              ><strong>{{ t('network.system') }}</strong
              ><small>{{ t('network.system_desc') }}</small></span
            >
            <span v-if="mode === 'system_proxy'" class="check"><Check :size="12" /></span>
          </button>
          <button
            type="button"
            class="mode"
            :class="{ active: mode === 'tun' }"
            @click="mode = 'tun'"
          >
            <span class="mode-icon"><Waypoints :size="19" /></span>
            <span
              ><strong>{{ t('network.tun') }}</strong
              ><small>{{ t('network.tun_desc') }}</small></span
            >
            <span v-if="mode === 'tun'" class="check"><Check :size="12" /></span>
          </button>
          <button
            type="button"
            class="mode"
            :class="{ active: mode === 'mixed' }"
            @click="mode = 'mixed'"
          >
            <span class="mode-icon"><Link2 :size="19" /></span>
            <span
              ><strong>{{ t('network.mixed') }}</strong
              ><small>{{ t('network.mixed_desc') }}</small></span
            >
            <span v-if="mode === 'mixed'" class="check"><Check :size="12" /></span>
          </button>
        </div>
        <div class="actions">
          <NButton secondary @click="step = 1">
            <template #icon><ArrowLeft :size="16" /></template>
            {{ t('common.back') }}
          </NButton>
          <div class="spacer" />
          <NButton type="primary" size="large" :loading="loading" @click="finish">{{
            t('onboarding.done')
          }}</NButton>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.onboarding {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px;
}
.top {
  width: 100%;
  max-width: 680px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0 24px;
}
.card {
  width: 100%;
  max-width: 680px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  background: var(--surface);
  box-shadow: var(--shadow-2);
  padding: 30px;
}
.head h1 {
  font-size: 25px;
  letter-spacing: -0.03em;
  margin-top: 6px;
}
.steps {
  display: flex;
  gap: 18px;
  margin-top: 18px;
  flex-wrap: wrap;
}
.step {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-3);
}
.step.active {
  color: var(--text);
}
.step.done {
  color: var(--text-2);
}
.dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  border: 1px solid var(--border);
  font-size: 9px;
}
.step.active .dot {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: var(--accent-soft);
}
.step.done .dot {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 35%, transparent);
}
.body {
  margin-top: 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.modes {
  display: flex;
  gap: 16px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}
.spacer {
  flex: 1;
}
.test-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.test-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--surface-2);
}
.test-icon {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--accent);
  background: var(--accent-soft);
}
.test-copy {
  flex: 1;
  min-width: 0;
}
.test-copy strong {
  display: block;
  font-size: 11.5px;
}
.mode-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mode {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 12px;
  border-radius: 11px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.mode.active {
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  background: var(--accent-soft);
}
.mode-icon {
  width: 36px;
  height: 36px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: var(--accent);
  background: var(--surface);
  border: 1px solid var(--border);
}
.mode span:nth-child(2) {
  flex: 1;
}
.mode strong {
  display: block;
  font-size: 12px;
}
.mode small {
  display: block;
  color: var(--text-2);
  font-size: 10.5px;
  line-height: 1.45;
}
.check {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--accent);
  background: var(--surface);
}
@media (max-width: 600px) {
  .card {
    padding: 20px;
  }
  .steps {
    gap: 10px;
  }
}
</style>
