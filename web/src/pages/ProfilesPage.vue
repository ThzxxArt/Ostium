<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, NModal, NRadio, NRadioGroup, useDialog, useMessage } from 'naive-ui'
import { Check, Link2, Plus, RefreshCw, ScanLine, Trash2, Waypoints } from '@lucide/vue'
import jsQR from 'jsqr'
import OPageHeader from '@/components/OPageHeader.vue'
import OStatusPill from '@/components/OStatusPill.vue'
import OEmptyState from '@/components/OEmptyState.vue'
import OErrorState from '@/components/OErrorState.vue'
import { api } from '@/api'
import type { Profile } from '@/api/types'
import { relativeTime } from '@/utils/format'

const { t, locale } = useI18n()
const message = useMessage()
const dialog = useDialog()

const profiles = ref<Profile[]>([])
const activeProfileId = ref<string | null>(null)
const dragId = ref<string | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const importOpen = ref(false)
const importMode = ref<'url' | 'text' | 'qr'>('url')
const importName = ref('')
const importUrl = ref('')
const importText = ref('')
const importing = ref(false)
const busy = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const cameraOpen = ref(false)
const videoRef = ref<HTMLVideoElement | null>(null)
let cameraStream: MediaStream | null = null
let scanHandle: number | null = null

const sorted = computed(() => [...profiles.value].sort((a, b) => a.sort_order - b.sort_order))

async function load() {
  loading.value = true
  try {
    const result = await api.profiles.list()
    profiles.value = result.profiles
    activeProfileId.value = result.active_profile_id
    error.value = null
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

async function activate(profile: Profile) {
  busy.value = profile.id
  try {
    const result = await api.profiles.activate(profile.id)
    if (result.warning) message.warning(result.warning)
    activeProfileId.value = profile.id
    message.success(t('profiles.activated'))
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = null
  }
}

async function toggleEnabled(profile: Profile) {
  busy.value = profile.id
  try {
    const result = await api.profiles.update(profile.id, { enabled: !profile.enabled })
    if (result.warning) message.warning(result.warning)
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = null
  }
}

function onDragStart(profile: Profile) {
  dragId.value = profile.id
}

async function onDrop(target: Profile) {
  const sourceId = dragId.value
  dragId.value = null
  if (!sourceId || sourceId === target.id) return
  const next = [...sorted.value]
  const from = next.findIndex((item) => item.id === sourceId)
  const to = next.findIndex((item) => item.id === target.id)
  if (from < 0 || to < 0) return
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  profiles.value = next.map((item, index) => ({ ...item, sort_order: index * 10 }))
  try {
    await api.profiles.reorder(next.map((item) => item.id))
    message.success(t('profiles.reordered'))
  } catch (err) {
    message.error((err as Error).message)
    await load()
  }
}

async function importProfile() {
  const name = importName.value.trim() || 'Imported'
  if (importMode.value === 'url' && !importUrl.value.trim()) return
  if (importMode.value !== 'url' && !importText.value.trim()) return
  importing.value = true
  try {
    const result = await api.profiles.create({
      name,
      url: importMode.value === 'url' ? importUrl.value.trim() : undefined,
      text: importMode.value === 'text' ? importText.value.trim() : undefined,
    })
    if (result.warning) message.warning(result.warning)
    message.success(t('profiles.add'))
    importOpen.value = false
    importUrl.value = ''
    importText.value = ''
    importName.value = ''
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    importing.value = false
  }
}

async function refresh(profile: Profile) {
  busy.value = profile.id
  try {
    const result = await api.profiles.refresh(profile.id)
    if (result.warning) message.warning(result.warning)
    message.success(t('profiles.refreshed'))
    await load()
  } catch (err) {
    message.error((err as Error).message)
  } finally {
    busy.value = null
  }
}

async function selectEndpoint(profile: Profile, tag: string) {
  try {
    await api.profiles.update(profile.id, { selected_endpoint: tag })
    profile.selected_endpoint = tag
    message.success(t('profiles.selected'))
  } catch (err) {
    message.error((err as Error).message)
  }
}

function remove(profile: Profile) {
  dialog.error({
    title: t('common.delete'),
    content: t('profiles.delete_confirm', { name: profile.name }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await api.profiles.remove(profile.id)
        message.success(t('common.delete'))
        await load()
      } catch (err) {
        message.error((err as Error).message)
      }
    },
  })
}

function pickQr() {
  fileInput.value?.click()
}

async function onQrFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const bitmap = await createImageBitmap(file)
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width
    canvas.height = bitmap.height
    const context = canvas.getContext('2d')
    if (!context) return
    context.drawImage(bitmap, 0, 0)
    const data = context.getImageData(0, 0, canvas.width, canvas.height)
    const code = jsQR(data.data, data.width, data.height)
    if (code?.data) {
      importText.value = code.data
      importMode.value = 'text'
      message.success(t('profiles.scan_qr'))
    } else {
      message.error(t('errors.validation'))
    }
  } catch {
    message.error(t('errors.validation'))
  } finally {
    input.value = ''
  }
}

function stopCamera() {
  if (scanHandle !== null) {
    cancelAnimationFrame(scanHandle)
    scanHandle = null
  }
  cameraStream?.getTracks().forEach((track) => track.stop())
  cameraStream = null
  cameraOpen.value = false
}

async function startCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    message.error(t('profiles.camera_failed'))
    return
  }
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' },
    })
    cameraOpen.value = true
    await nextTick()
    if (videoRef.value) {
      videoRef.value.srcObject = cameraStream
      await videoRef.value.play()
    }
    scanFrame()
  } catch {
    stopCamera()
    message.error(t('profiles.camera_failed'))
  }
}

function scanFrame() {
  scanHandle = requestAnimationFrame(() => {
    const video = videoRef.value
    if (!video || video.readyState < 2) {
      scanFrame()
      return
    }
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const context = canvas.getContext('2d')
    if (!context) {
      stopCamera()
      return
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height)
    const data = context.getImageData(0, 0, canvas.width, canvas.height)
    const code = jsQR(data.data, data.width, data.height)
    if (code?.data) {
      importText.value = code.data
      importMode.value = 'text'
      stopCamera()
      message.success(t('profiles.scan_qr'))
      return
    }
    scanFrame()
  })
}

onBeforeUnmount(stopCamera)

onMounted(load)
</script>

<template>
  <div class="o-page">
    <OPageHeader :title="t('profiles.title')" :subtitle="t('profiles.subtitle')">
      <template #actions>
        <NButton secondary :loading="loading" @click="load">
          <template #icon><RefreshCw :size="15" /></template>
          {{ t('common.refresh') }}
        </NButton>
        <NButton type="primary" @click="importOpen = true">
          <template #icon><Plus :size="16" /></template>
          {{ t('profiles.add') }}
        </NButton>
      </template>
    </OPageHeader>

    <OErrorState v-if="error" :message="error" @retry="load" />

    <div v-else-if="!loading && !profiles.length" class="o-card">
      <OEmptyState
        :title="t('profiles.empty_title')"
        :description="t('profiles.empty_desc')"
        :icon="Link2"
      >
        <NButton type="primary" @click="importOpen = true">{{ t('profiles.add') }}</NButton>
      </OEmptyState>
    </div>

    <div v-else class="profile-grid">
      <article
        v-for="profile in sorted"
        :key="profile.id"
        class="profile o-card"
        :class="{ active: activeProfileId === profile.id, dragging: dragId === profile.id }"
        draggable="true"
        @dragstart="onDragStart(profile)"
        @dragover.prevent
        @drop.prevent="onDrop(profile)"
      >
        <header class="profile-head">
          <div class="profile-icon"><Waypoints :size="19" /></div>
          <div class="profile-copy">
            <h2>{{ profile.name }}</h2>
            <span class="o-micro o-subtle"
              >{{ profile.kind }} · {{ profile.endpoints.length }}
              {{ t('profiles.endpoints') }}</span
            >
          </div>
          <OStatusPill
            :status="
              activeProfileId === profile.id ? 'online' : profile.enabled ? 'active' : 'disabled'
            "
            :label="activeProfileId === profile.id ? t('profiles.active') : undefined"
            size="sm"
          />
        </header>

        <div class="endpoints">
          <button
            v-for="endpoint in profile.endpoints"
            :key="endpoint.tag"
            type="button"
            class="endpoint"
            :class="{
              active:
                profile.selected_endpoint === endpoint.tag ||
                (!profile.selected_endpoint && profile.endpoints[0]?.tag === endpoint.tag),
            }"
            @click="selectEndpoint(profile, endpoint.tag)"
          >
            <span class="endpoint-radio">
              <Check
                v-if="
                  profile.selected_endpoint === endpoint.tag ||
                  (!profile.selected_endpoint && profile.endpoints[0]?.tag === endpoint.tag)
                "
                :size="11"
              />
            </span>
            <span class="endpoint-copy">
              <strong>{{ endpoint.name }}</strong>
              <small>{{ endpoint.server }}:{{ endpoint.port }}</small>
            </span>
            <span class="protocol">{{ endpoint.protocol }}</span>
          </button>
          <p v-if="!profile.endpoints.length" class="o-small o-subtle">
            {{ t('profiles.no_endpoints') }}
          </p>
        </div>

        <p v-if="profile.last_refresh_error" class="refresh-error">
          {{ profile.last_refresh_error }}
        </p>

        <footer class="profile-foot">
          <span class="o-micro o-subtle"
            >{{ t('profiles.last_refresh') }}:
            {{
              profile.last_refresh_at
                ? relativeTime(profile.last_refresh_at, locale)
                : t('common.never')
            }}</span
          >
          <div class="profile-actions">
            <NButton
              v-if="activeProfileId !== profile.id && profile.enabled"
              size="tiny"
              secondary
              :loading="busy === profile.id"
              @click="activate(profile)"
            >
              <template #icon><Check :size="13" /></template>
              {{ t('profiles.activate') }}
            </NButton>
            <NButton
              size="tiny"
              secondary
              :loading="busy === profile.id"
              @click="toggleEnabled(profile)"
            >
              {{ profile.enabled ? t('common.disable') : t('common.enable') }}
            </NButton>
            <NButton
              v-if="profile.subscription_url"
              size="tiny"
              secondary
              :loading="busy === profile.id"
              @click="refresh(profile)"
            >
              <template #icon><RefreshCw :size="13" /></template>
              {{ t('profiles.refresh') }}
            </NButton>
            <NButton size="tiny" quaternary type="error" @click="remove(profile)">
              <template #icon><Trash2 :size="13" /></template>
            </NButton>
          </div>
        </footer>
      </article>
    </div>

    <NModal
      v-model:show="importOpen"
      preset="card"
      :style="{ width: 'min(600px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <template #header>{{ t('profiles.add') }}</template>
      <div class="import-form">
        <label class="field">
          <span>{{ t('profiles.name') }}</span>
          <NInput v-model:value="importName" placeholder="My server" />
        </label>
        <NRadioGroup v-model:value="importMode" class="mode-tabs">
          <NRadio value="url">{{ t('profiles.import_url') }}</NRadio>
          <NRadio value="text">{{ t('profiles.import_text') }}</NRadio>
          <NRadio value="qr">{{ t('profiles.scan_qr') }}</NRadio>
        </NRadioGroup>
        <label v-if="importMode === 'url'" class="field">
          <span>{{ t('profiles.import_url') }}</span>
          <NInput v-model:value="importUrl" placeholder="https://example.com/sub/token" />
          <small class="o-subtle">{{ t('profiles.url_hint') }}</small>
        </label>
        <label v-else-if="importMode === 'text'" class="field">
          <span>{{ t('profiles.import_text') }}</span>
          <NInput
            v-model:value="importText"
            type="textarea"
            :autosize="{ minRows: 6, maxRows: 12 }"
          />
          <small class="o-subtle">{{ t('profiles.url_hint') }}</small>
        </label>
        <div v-else class="qr-import">
          <input ref="fileInput" type="file" accept="image/*" hidden @change="onQrFile" />
          <button type="button" class="qr-drop" @click="pickQr">
            <ScanLine :size="30" />
            <strong>{{ t('profiles.scan_qr') }}</strong>
            <span>{{ t('profiles.qr_hint') }}</span>
          </button>
          <NButton secondary block @click="startCamera">{{ t('profiles.use_camera') }}</NButton>
          <p v-if="importText" class="o-small o-muted o-truncate">{{ importText }}</p>
        </div>
      </div>
      <template #footer>
        <div class="modal-actions">
          <NButton secondary @click="importOpen = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="importing" @click="importProfile">{{
            t('profiles.add')
          }}</NButton>
        </div>
      </template>
    </NModal>

    <NModal
      v-model:show="cameraOpen"
      preset="card"
      :title="t('profiles.use_camera')"
      :style="{ width: 'min(520px, calc(100vw - 32px))' }"
      @after-leave="stopCamera"
    >
      <p class="o-small o-muted">{{ t('profiles.camera_hint') }}</p>
      <video ref="videoRef" class="camera-preview" muted playsinline />
      <template #footer>
        <div class="modal-actions">
          <NButton secondary @click="stopCamera">{{ t('common.cancel') }}</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.profile-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.profile {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  cursor: grab;
}
.profile.active {
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 25%, transparent);
}
.profile.dragging {
  opacity: 0.55;
}
.profile-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.profile-icon {
  width: 38px;
  height: 38px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: var(--accent);
  background: var(--accent-soft);
}
.profile-copy {
  flex: 1;
  min-width: 0;
}
.profile-copy h2 {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.endpoints {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.endpoint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 9px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text);
  cursor: pointer;
  text-align: left;
}
.endpoint.active {
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  background: var(--accent-soft);
}
.endpoint-radio {
  width: 16px;
  height: 16px;
  flex: none;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  display: grid;
  place-items: center;
  color: var(--accent);
}
.endpoint.active .endpoint-radio {
  border-color: var(--accent);
}
.endpoint-copy {
  flex: 1;
  min-width: 0;
}
.endpoint-copy strong {
  display: block;
  font-size: 11px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.endpoint-copy small {
  font-size: 9.5px;
  color: var(--text-3);
}
.protocol {
  font-size: 8.5px;
  font-family: var(--font-mono);
  color: var(--text-3);
  text-transform: uppercase;
}
.refresh-error {
  padding: 7px 9px;
  border-radius: 8px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 10px;
  line-height: 1.45;
}
.profile-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.profile-actions {
  display: flex;
  gap: 4px;
}
.import-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.mode-tabs {
  display: flex;
  gap: 16px;
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
.qr-drop {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  padding: 30px 16px;
  border-radius: 12px;
  border: 1px dashed var(--border-strong);
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
}
.qr-drop:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.qr-drop strong {
  font-size: 12.5px;
}
.qr-drop span {
  color: var(--text-3);
  font-size: 10.5px;
}
.camera-preview {
  width: 100%;
  margin-top: 10px;
  border-radius: 12px;
  background: #000;
  min-height: 220px;
  object-fit: cover;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
@media (max-width: 1000px) {
  .profile-grid {
    grid-template-columns: 1fr;
  }
}
</style>
