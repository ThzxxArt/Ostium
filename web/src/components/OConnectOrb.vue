<script setup lang="ts">
import { computed } from 'vue'
import { Power } from '@lucide/vue'

const props = withDefaults(
  defineProps<{
    state: 'connected' | 'connecting' | 'disconnected'
    label?: string
    sublabel?: string
    disabled?: boolean
    size?: number
  }>(),
  { size: 208 },
)

defineEmits<{ toggle: [] }>()

const color = computed(() => {
  if (props.state === 'connected') return 'var(--success)'
  if (props.state === 'connecting') return 'var(--accent)'
  return 'var(--text-3)'
})
</script>

<template>
  <div class="orb-wrap" :style="{ '--orb-size': `${size}px`, '--orb-color': color }">
    <button
      type="button"
      class="orb"
      :class="state"
      :disabled="disabled"
      :aria-label="label || state"
      :aria-pressed="state === 'connected'"
      @click="$emit('toggle')"
    >
      <span class="aura" aria-hidden="true" />
      <span class="ring ring-1" aria-hidden="true" />
      <span class="ring ring-2" aria-hidden="true" />
      <span class="core">
        <Power :size="42" :stroke-width="1.5" />
      </span>
    </button>
    <div class="caption">
      <strong>{{ label || state }}</strong>
      <span v-if="sublabel">{{ sublabel }}</span>
    </div>
  </div>
</template>

<style scoped>
.orb-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}
.orb {
  position: relative;
  width: var(--orb-size);
  height: var(--orb-size);
  border-radius: 50%;
  border: 0;
  background: transparent;
  cursor: pointer;
  display: grid;
  place-items: center;
  color: var(--orb-color);
  isolation: isolate;
}
.orb:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.aura {
  position: absolute;
  inset: 12%;
  border-radius: 50%;
  background:
    radial-gradient(
      circle at 34% 26%,
      color-mix(in srgb, var(--orb-color) 34%, transparent),
      transparent 58%
    ),
    radial-gradient(
      circle at 70% 78%,
      color-mix(in srgb, var(--accent-2) 22%, transparent),
      transparent 56%
    ),
    var(--surface);
  border: 1px solid color-mix(in srgb, var(--orb-color) 30%, var(--border));
  box-shadow:
    inset 0 1px 1px rgba(255, 255, 255, 0.08),
    0 24px 70px color-mix(in srgb, var(--orb-color) 18%, transparent);
  transition:
    transform 240ms var(--ease),
    box-shadow 240ms var(--ease);
}
.orb:hover .aura {
  transform: scale(1.02);
  box-shadow:
    inset 0 1px 1px rgba(255, 255, 255, 0.1),
    0 28px 82px color-mix(in srgb, var(--orb-color) 26%, transparent);
}
.ring {
  position: absolute;
  border-radius: 50%;
  border: 1px solid color-mix(in srgb, var(--orb-color) 24%, transparent);
  pointer-events: none;
}
.ring-1 {
  inset: 2%;
  border-style: dashed;
  opacity: 0.7;
}
.ring-2 {
  inset: -4%;
  opacity: 0.35;
}
.connected .ring-1 {
  animation: spin 18s linear infinite;
}
.connected .aura {
  animation: breathe 3.4s var(--ease) infinite;
}
.connected .core {
  animation: breathe 3.4s var(--ease) infinite;
}
.connecting .ring-1 {
  animation: spin 2.6s linear infinite;
  border-color: color-mix(in srgb, var(--orb-color) 55%, transparent);
}
.connecting .ring-2 {
  animation: ping 1.8s var(--ease) infinite;
}
.connecting .aura {
  animation: pulse-soft 1.8s var(--ease) infinite;
}
.disconnected .aura {
  filter: saturate(0.55);
}
.core {
  position: relative;
  z-index: 1;
  width: 88px;
  height: 88px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: var(--orb-color);
  background: color-mix(in srgb, var(--orb-color) 10%, var(--bg));
  border: 1px solid color-mix(in srgb, var(--orb-color) 32%, transparent);
  box-shadow:
    inset 0 0 24px color-mix(in srgb, var(--orb-color) 18%, transparent),
    0 0 40px color-mix(in srgb, var(--orb-color) 12%, transparent);
}
.caption {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}
.caption strong {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.caption span {
  color: var(--text-2);
  font-size: 12px;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes breathe {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.015);
  }
}
@keyframes ping {
  0% {
    transform: scale(0.96);
    opacity: 0.5;
  }
  100% {
    transform: scale(1.08);
    opacity: 0;
  }
}
@keyframes pulse-soft {
  0%,
  100% {
    opacity: 0.9;
  }
  50% {
    opacity: 1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .ring,
  .aura,
  .core {
    animation: none !important;
  }
}
</style>
