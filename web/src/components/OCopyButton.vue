<script setup lang="ts">
import { ref } from 'vue'
import { Check, Copy } from '@lucide/vue'
import { useMessage } from 'naive-ui'

const props = withDefaults(
  defineProps<{
    value: string
    label?: string
    size?: 'tiny' | 'small' | 'medium'
    secondary?: boolean
    block?: boolean
  }>(),
  { size: 'small' },
)

const message = useMessage()
const copied = ref(false)

async function copy() {
  let ok = false
  try {
    await navigator.clipboard.writeText(props.value)
    ok = true
  } catch {
    const area = document.createElement('textarea')
    area.value = props.value
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    try {
      ok = document.execCommand('copy')
    } finally {
      document.body.removeChild(area)
    }
  }
  if (ok) {
    copied.value = true
    window.setTimeout(() => (copied.value = false), 1500)
    message.success('Copied')
  } else {
    message.error('Copy failed; select the text manually')
  }
}
</script>

<template>
  <button
    type="button"
    class="copy"
    :class="[`size-${size}`, { secondary, block }]"
    :aria-label="label || 'Copy'"
    @click.stop="copy"
  >
    <component :is="copied ? Check : Copy" :size="size === 'tiny' ? 13 : 15" :stroke-width="1.8" />
    <span v-if="label">{{ copied ? 'Copied' : label }}</span>
  </button>
</template>

<style scoped>
.copy {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  transition:
    color var(--dur) var(--ease),
    border-color var(--dur) var(--ease),
    background var(--dur) var(--ease);
}
.copy:hover {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
}
.copy.size-tiny {
  height: 26px;
  width: 26px;
  padding: 0;
  border-radius: 7px;
}
.copy.size-medium {
  height: 38px;
  padding: 0 14px;
}
.copy.secondary {
  background: transparent;
}
.copy.block {
  width: 100%;
}
</style>
