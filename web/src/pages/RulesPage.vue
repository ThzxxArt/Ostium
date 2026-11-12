<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, NModal, NSelect, NSwitch, useDialog, useMessage } from 'naive-ui'
import { Ban, Compass, Database, Plus, RefreshCw, Route, Trash2, Zap } from '@lucide/vue'
import OPageHeader from '@/components/OPageHeader.vue'
import OSectionCard from '@/components/OSectionCard.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import { api } from '@/api'
import type { Rule, RuleSet } from '@/api/types'

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()

const rules = ref<Rule[]>([])
const ruleSets = ref<RuleSet[]>([])
const loading = ref(true)
const ruleOpen = ref(false)
const ruleSetOpen = ref(false)
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
    | 'process_name',
  values: '',
  note: '',
})
const ruleSetForm = ref({ name: '', url: '', format: 'binary' })

const typeOptions = [
  { label: t('rules.domain'), value: 'domain' },
  { label: t('rules.domain_suffix'), value: 'domain_suffix' },
  { label: t('rules.domain_keyword'), value: 'domain_keyword' },
  { label: t('rules.domain_regex'), value: 'domain_regex' },
  { label: t('rules.ip_cidr'), value: 'ip_cidr' },
  { label: t('rules.port'), value: 'port' },
  { label: t('rules.process'), value: 'process_name' },
]
const actionOptions = [
  { label: t('rules.action_proxy'), value: 'proxy' },
  { label: t('rules.action_direct'), value: 'direct' },
  { label: t('rules.action_block'), value: 'block' },
]

async function load() {
  loading.value = true
  try {
    const [ruleData, setData] = await Promise.all([api.rules.list(), api.rules.ruleSets()])
    rules.value = ruleData.rules
    ruleSets.value = setData.rule_sets
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    loading.value = false
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
  if (!values.length) return
  const match = { [form.value.type]: form.value.type === 'port' ? values.map(Number) : values }
  try {
    if (editing.value)
      await api.rules.update(editing.value.id, {
        action: form.value.action,
        match,
        note: form.value.note,
      })
    else await api.rules.create({ action: form.value.action, match, note: form.value.note })
    ruleOpen.value = false
    await load()
  } catch (err) {
    message.error((err as Error).message)
  }
}

async function toggleRule(rule: Rule, enabled: boolean) {
  try {
    await api.rules.update(rule.id, { enabled })
    rule.enabled = enabled
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
        await api.rules.remove(rule.id)
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

async function addRuleSet() {
  if (!ruleSetForm.value.name || !ruleSetForm.value.url) return
  try {
    await api.rules.addRuleSet(ruleSetForm.value)
    ruleSetOpen.value = false
    ruleSetForm.value = { name: '', url: '', format: 'binary' }
    await load()
  } catch (err) {
    message.error((err as Error).message)
  }
}

async function updateRuleSet(ruleSet: RuleSet) {
  try {
    await api.rules.updateRuleSet(ruleSet.id)
    message.success(t('rules.applied'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  }
}

function removeRuleSet(ruleSet: RuleSet) {
  dialog.warning({
    title: t('common.delete'),
    content: t('common.delete_confirm'),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.rules.removeRuleSet(ruleSet.id)
        await load()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

function matchSummary(rule: Rule): string {
  return Object.entries(rule.match || {})
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
    .join(' · ')
}

function actionTone(action: string): string {
  return action === 'direct' ? 'direct' : action === 'block' ? 'block' : 'proxy'
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
            <strong :class="String(testResult.action || 'proxy')">
              {{ testResult.matched ? (testResult.rule as Rule)?.action : t('rules.no_match') }}
            </strong>
          </div>
          <p v-if="testResult.matched" class="o-small o-muted">
            {{ matchSummary(testResult.rule as Rule) }}
          </p>
        </div>
      </OSectionCard>
    </div>

    <OSectionCard :title="t('rules.rule_sets')" :icon="Database">
      <template #actions>
        <NButton size="small" secondary @click="ruleSetOpen = true">
          <template #icon><Plus :size="14" /></template>
          {{ t('rules.add_rule_set') }}
        </NButton>
      </template>
      <p class="o-small o-muted">{{ t('rules.rule_set_hint') }}</p>
      <OEmptyState
        v-if="!ruleSets.length"
        compact
        :title="t('rules.rule_sets')"
        :description="t('rules.rule_set_hint')"
      />
      <div v-else class="ruleset-list">
        <div v-for="ruleSet in ruleSets" :key="ruleSet.id" class="ruleset">
          <div class="ruleset-copy">
            <strong>{{ ruleSet.name }}</strong>
            <span class="o-micro o-subtle o-truncate">{{ ruleSet.url }}</span>
            <small v-if="ruleSet.last_error" class="error">{{ ruleSet.last_error }}</small>
          </div>
          <NButton size="tiny" secondary @click="updateRuleSet(ruleSet)">{{
            t('rules.update_rule_set')
          }}</NButton>
          <NButton size="tiny" quaternary type="error" @click="removeRuleSet(ruleSet)">
            <template #icon><Trash2 :size="13" /></template>
          </NButton>
        </div>
      </div>
    </OSectionCard>

    <NModal
      v-model:show="ruleOpen"
      preset="card"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ editing ? t('rules.edit') : t('rules.add') }}</template>
      <div class="form">
        <label class="field"
          ><span>{{ t('rules.action') }}</span
          ><NSelect v-model:value="form.action" :options="actionOptions"
        /></label>
        <label class="field"
          ><span>{{ t('rules.match') }}</span
          ><NSelect v-model:value="form.type" :options="typeOptions"
        /></label>
        <label class="field"
          ><span>{{ t('rules.match') }}</span
          ><NInput v-model:value="form.values" placeholder=".example.com, example.org"
        /></label>
        <label class="field"
          ><span>{{ t('common.note') }}</span
          ><NInput v-model:value="form.note"
        /></label>
      </div>
      <template #footer>
        <div class="modal-actions">
          <NButton secondary @click="ruleOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" @click="saveRule">{{ t('common.save') }}</NButton>
        </div>
      </template>
    </NModal>

    <NModal
      v-model:show="ruleSetOpen"
      preset="card"
      :style="{ width: 'min(520px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('rules.add_rule_set') }}</template>
      <div class="form">
        <label class="field"
          ><span>{{ t('common.name') }}</span
          ><NInput v-model:value="ruleSetForm.name" placeholder="geosite-cn"
        /></label>
        <label class="field"
          ><span>URL</span
          ><NInput v-model:value="ruleSetForm.url" placeholder="https://example.com/rules.srs"
        /></label>
        <label class="field"
          ><span>{{ t('common.type') }}</span
          ><NSelect
            v-model:value="ruleSetForm.format"
            :options="[
              { label: 'binary (.srs)', value: 'binary' },
              { label: 'source', value: 'source' },
            ]"
        /></label>
      </div>
      <template #footer>
        <div class="modal-actions">
          <NButton secondary @click="ruleSetOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" @click="addRuleSet">{{ t('common.add') }}</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.split {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 0.8fr);
  gap: 20px;
  align-items: start;
  margin-bottom: 20px;
}
.rule-list,
.ruleset-list {
  display: flex;
  flex-direction: column;
}
.rule,
.ruleset {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
}
.rule:last-child,
.ruleset:last-child {
  border-bottom: 0;
}
.action {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 9px;
  text-transform: uppercase;
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
.rule-copy,
.ruleset-copy {
  flex: 1;
  min-width: 0;
}
.rule-copy strong,
.ruleset-copy strong {
  display: block;
  font-size: 11px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ruleset-copy span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ruleset-copy .error {
  color: var(--danger);
  font-size: 9.5px;
  display: block;
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
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
@media (max-width: 1100px) {
  .split {
    grid-template-columns: 1fr;
  }
}
</style>
