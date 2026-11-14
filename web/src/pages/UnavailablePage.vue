<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton } from 'naive-ui'
import { RefreshCw, ServerCrash } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n()
const retrying = ref(false)

async function retry() {
  retrying.value = true
  try {
    await auth.bootstrap(true)
    if (auth.statusState === 'ready') {
      await router.replace(auth.authenticated ? '/' : '/login')
    }
  } finally {
    retrying.value = false
  }
}
</script>

<template>
  <main class="unavailable" role="main">
    <div class="card">
      <span class="icon"><ServerCrash :size="28" /></span>
      <h1>{{ t('connection_error_title') }}</h1>
      <p>{{ t('connection_error_desc') }}</p>
      <p v-if="auth.error" class="detail">{{ auth.error }}</p>
      <div class="actions">
        <NButton type="primary" :loading="retrying" @click="retry">
          <template #icon><RefreshCw :size="16" /></template>
          {{ t('retry') }}
        </NButton>
        <NButton quaternary @click="router.replace('/login')">{{ t('open_login') }}</NButton>
      </div>
    </div>
  </main>
</template>

<style scoped>
.unavailable {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--bg);
}
.card {
  width: min(460px, 100%);
  padding: 36px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
  text-align: center;
}
.icon {
  display: inline-grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: 14px;
  color: var(--warning, #d97706);
  background: var(--warning-soft, rgba(217, 119, 6, 0.12));
  margin-bottom: 18px;
}
h1 {
  font-size: 22px;
  letter-spacing: -0.02em;
}
p {
  margin-top: 10px;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.65;
}
.detail {
  font-family: var(--mono, monospace);
  font-size: 11px;
  color: var(--text-3);
  word-break: break-word;
}
.actions {
  margin-top: 24px;
  display: flex;
  gap: 10px;
  justify-content: center;
  flex-wrap: wrap;
}
</style>
