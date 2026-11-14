<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, NModal, NSelect, NSwitch, useDialog, useMessage } from 'naive-ui'
import {
  Ban,
  CheckCircle2,
  Compass,
  Globe2,
  ListFilter,
  Plus,
  RefreshCw,
  Route,
  Sparkles,
  Trash2,
  Zap,
} from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OSectionCard from '@/components/OSectionCard.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { AppSettings, Rule } from '@/api/types'

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()

const rules = ref<Rule[]>([])
const settings = ref<AppSettings | null>(null)
const loading = ref(true)
const ruleOpen = ref(false)
const editing = ref<Rule | null>(null)
const testDomain = ref('')
const testResult = ref<Record<string, unknown> | null>(null)
const testing = ref(false)

const form = ref({
  action: 'proxy' as 'proxy' | 'direct' | 'block',
  type: 'domain_suffix' as
    | 'domain'
    | 'domain_suffix'
    | 'domain_keyword'
    | 'domain_regex'
    | 'ip_cidr'
    | 'port'
    | 'source_port'
    | 'protocol'
    | 'process_name',
  values: '',
  note: '',
})

const presets = computed(() => [
  { id: 'smart', title: t('rules.smart'), description: t('rules.smart_desc'), icon: Sparkles },
  { id: 'global', title: t('rules.global'), description: t('rules.global_desc'), icon: Globe2 },
  { id: 'direct', title: t('rules.direct'), description: t('rules.direct_desc'), icon: Compass },
  { id: 'custom', title: t('rules.custom'), description: t('rules.custom_desc'), icon: ListFilter },
])
const activePreset = computed(() => settings.value?.general.routing_mode || 'smart')

const typeOptions = computed(() => [
  { label: t('rules.domain'), value: 'domain' },
  { label: t('rules.domain_suffix'), value: 'domain_suffix' },
  { label: t('rules.domain_keyword'), value: 'domain_keyword' },
  { label: t('rules.domain_regex'), value: 'domain_regex' },
  { label: t('rules.ip_cidr'), value: 'ip_cidr' },
  { label: t('rules.port'), value: 'port' },
  { label: t('rules.source_port'), value: 'source_port' },
  { label: t('rules.protocol'), value: 'protocol' },
  { label: t('rules.process'), value: 'process_name' },
])
const actionOptions = computed(() => [
  { label: t('rules.action_proxy'), value: 'proxy' },
  { label: t('rules.action_direct'), value: 'direct' },
  { label: t('rules.action_block'), value: 'block' },
])

async function load() {
  loading.value = true
  try {
    const [ruleData, settingsData] = await Promise.all([api.rules.list(), api.settings.get()])
    rules.value = ruleData.rules
    settings.value = settingsData
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function setPreset(id: string) {
  try {
    const result = await api.settings.update({ routing_mode: id })
    if (settings.value) settings.value.general.routing_mode = id
    if (result.warning) message.warning(result.warning)
    else message.success(t('rules.applied'))
  } catch (err) {
    message.error((err as Error).message)
  }
}

function openAdd() {
  editing.value = null
  form.value = { action: 'proxy', type: 'domain_suffix', values: '', note: '' }
  ruleOpen.value = true
}

function openEdit(rule: Rule) {
  editing.value = rule
  const match = rule.match || {}
  const type = (Object.keys(match)[0] || 'domain_suffix') as typeof form.value.type
  const raw = match[type]
  form.value = {
    action: rule.action,
    type,
    values: Array.isArray(raw) ? raw.join(', ') : String(raw || ''),
    note: rule.note,
  }
  ruleOpen.value = true
}

async function saveRule() {
  const values = form.value.values
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean)
  if (!values.length) {
    message.error(t('errors.validation'))
    return
  }
  const numeric = form.value.type === 'port' || form.value.type === 'source_port'
  const match = { [form.value.type]: numeric ? values.map(Number) : values }
  try {
    const result = editing.value
      ? await api.rules.update(editing.value.id, {
          action: form.value.action,
          match,
          note: form.value.note,
        })
      : await api.rules.create({ action: form.value.action, match, note: form.value.note })
    if (result.warning) message.warning(result.warning)
    else message.success(t('rules.applied'))
    ruleOpen.value = false
    await load()
  } catch (err) {
    message.error((err as Error).message)
  }
}

async function toggleRule(rule: Rule, enabled: boolean) {
  try {
    const result = await api.rules.update(rule.id, { enabled })
    rule.enabled = enabled
    if (result.warning) message.warning(result.warning)
  } catch (err) {
    message.error((err as Error).message)
  }
}

function removeRule(rule: Rule) {
  dialog.warning({
    title: t('common.delete'),
    content: t('common.delete_confirm'),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        const result = await api.rules.remove(rule.id)
        if (result.warning) message.warning(result.warning)
        await load()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

async function testRule() {
  if (!testDomain.value.trim()) return
  testing.value = true
  try {
    const isIp = /^\d+\.\d+\.\d+\.\d+/.test(testDomain.value.trim())
    testResult.value = await api.rules.test(
      isIp ? { ip: testDomain.value.trim() } : { domain: testDomain.value.trim() },
    )
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    testing.value = false
  }
}

function matchSummary(rule: Rule): string {
  return Object.entries(rule.match || {})
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
    .join(' · ')
}

function actionTone(action: string): string {
  if (action === 'direct') return 'direct'
  if (action === 'block') return 'block'
  return 'proxy'
}

onMounted(load)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('rules.title')" :subtitle="t('rules.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton type="primary" @click="openAdd">
          <template #icon><Plus :size="16" /></template>
          {{ t('rules.add') }}
        </NButton>
      </template>
    </OPageHeader>

    <div class="preset-grid">
      <button
        v-for="preset in presets"
        :key="preset.id"
        type="button"
        class="preset"
        :class="{ active: activePreset === preset.id }"
        @click="setPreset(preset.id)"
      >
        <span class="preset-icon"><component :is="preset.icon" :size="20" /></span>
        <span class="preset-copy">
          <strong>{{ preset.title }}</strong>
          <span>{{ preset.description }}</span>
        </span>
        <CheckCircle2 v-if="activePreset === preset.id" :size="17" class="check" />
      </button>
    </div>

    <div class="split">
      <OSectionCard :title="t('rules.custom')" :icon="Route">
        <OEmptyState
          v-if="!rules.length"
          compact
          :title="t('rules.empty_title')"
          :description="t('rules.empty_desc')"
        >
          <NButton type="primary" size="small" @click="openAdd">{{ t('rules.add') }}</NButton>
        </OEmptyState>
        <div v-else class="rule-list">
          <div v-for="rule in rules" :key="rule.id" class="rule">
            <span class="action" :class="actionTone(rule.action)">
              <component
                :is="rule.action === 'block' ? Ban : rule.action === 'direct' ? Compass : Zap"
                :size="12"
              />
              {{ rule.action }}
            </span>
            <div class="rule-copy">
              <strong>{{ matchSummary(rule) }}</strong>
              <span class="o-micro o-subtle">{{ rule.note || t('common.none') }}</span>
            </div>
            <NSwitch
              :value="rule.enabled"
              size="small"
              :aria-label="matchSummary(rule)"
              @update:value="(value: boolean) => toggleRule(rule, value)"
            />
            <NButton size="tiny" quaternary @click="openEdit(rule)">{{ t('common.edit') }}</NButton>
            <NButton size="tiny" quaternary type="error" @click="removeRule(rule)">
              <template #icon><Trash2 :size="13" /></template>
            </NButton>
          </div>
        </div>
      </OSectionCard>

      <OSectionCard :title="t('rules.test')" :icon="Zap">
        <p class="o-small o-muted">{{ t('rules.test_hint') }}</p>
        <div class="test-row">
          <NInput v-model:value="testDomain" placeholder="example.com" @keyup.enter="testRule" />
          <NButton type="primary" :loading="testing" @click="testRule">{{
            t('common.test')
          }}</NButton>
        </div>
        <div v-if="testResult" class="test-result">
          <div class="result-line">
            <span>{{ t('rules.test_result') }}</span>
            <strong :class="String(testResult.action || (testResult.matched ? 'proxy' : 'proxy'))">
              {{ testResult.matched ? (testResult.rule as Rule)?.action : t('rules.no_match') }}
            </strong>
          </div>
          <p v-if="testResult.matched" class="o-small o-muted">
            {{ matchSummary(testResult.rule as Rule) }}
          </p>
        </div>
      </OSectionCard>
    </div>

    <NModal
      v-model:show="ruleOpen"
      preset="card"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ editing ? t('rules.edit') : t('rules.add') }}</template>
      <div class="form">
        <label class="field">
          <span>{{ t('rules.action') }}</span>
          <NSelect v-model:value="form.action" :options="actionOptions" />
        </label>
        <label class="field">
          <span>{{ t('rules.match') }}</span>
          <NSelect v-model:value="form.type" :options="typeOptions" />
        </label>
        <label class="field">
          <span>{{ t('rules.match') }}</span>
          <NInput
            v-model:value="form.values"
            :placeholder="form.type === 'port' ? '443, 8443' : '.example.com, example.org'"
          />
          <small class="o-subtle">{{ t('rules.custom_desc') }}</small>
        </label>
        <label class="field">
          <span>{{ t('common.note') }}</span>
          <NInput v-model:value="form.note" />
        </label>
      </div>
      <template #footer>
        <div class="modal-actions">
          <NButton secondary @click="ruleOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" @click="saveRule">{{ t('common.save') }}</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.preset-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.preset {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px;
  border-radius: 13px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  text-align: left;
  position: relative;
}
.preset:hover {
  border-color: var(--border-strong);
}
.preset.active {
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: var(--accent-soft);
}
.preset-icon {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: var(--accent);
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.preset-copy {
  flex: 1;
  min-width: 0;
}
.preset-copy strong {
  display: block;
  font-size: 12px;
}
.preset-copy span {
  display: block;
  color: var(--text-2);
  font-size: 10.5px;
  line-height: 1.45;
  margin-top: 2px;
}
.check {
  color: var(--accent);
  flex: none;
}
.split {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 0.8fr);
  gap: 20px;
  align-items: start;
}
.rule-list {
  display: flex;
  flex-direction: column;
}
.rule {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
}
.rule:last-child {
  border-bottom: 0;
}
.action {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 6px;
  border-radius: 5px;
  flex: none;
}
.action.proxy {
  color: var(--accent);
  background: var(--accent-soft);
}
.action.direct {
  color: var(--info);
  background: var(--accent-soft-2);
}
.action.block {
  color: var(--danger);
  background: var(--danger-soft);
}
.rule-copy {
  flex: 1;
  min-width: 0;
}
.rule-copy strong {
  display: block;
  font-size: 11px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.test-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.test-result {
  margin-top: 14px;
  padding: 12px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.result-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 11.5px;
}
.result-line span {
  color: var(--text-3);
}
.result-line strong.proxy {
  color: var(--accent);
}
.result-line strong.direct {
  color: var(--info);
}
.result-line strong.block {
  color: var(--danger);
}
.form {
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
.field small {
  line-height: 1.5;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
@media (max-width: 1100px) {
  .preset-grid {
    grid-template-columns: 1fr 1fr;
  }
  .split {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 600px) {
  .preset-grid {
    grid-template-columns: 1fr;
  }
}
</style>
