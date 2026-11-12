<script setup lang="ts">
withDefaults(defineProps<{ size?: number; wordmark?: boolean }>(), { size: 34, wordmark: true })
</script>

<template>
  <div class="brand">
    <svg :width="size" :height="size" viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient
          id="ostium-ring"
          x1="6"
          y1="8"
          x2="44"
          y2="40"
          gradientUnits="userSpaceOnUse"
        >
          <stop stop-color="#5EEAD4" />
          <stop offset="1" stop-color="#60A5FA" />
        </linearGradient>
        <radialGradient
          id="ostium-core"
          cx="0"
          cy="0"
          r="1"
          gradientTransform="translate(24 24) rotate(90) scale(16)"
        >
          <stop stop-color="#0B1220" />
          <stop offset="1" stop-color="#111C31" />
        </radialGradient>
      </defs>
      <circle cx="24" cy="24" r="20" stroke="url(#ostium-ring)" stroke-width="1.6" opacity=".55" />
      <path
        d="M15 33V17.5C15 15.6 16.6 14 18.5 14H30"
        stroke="url(#ostium-ring)"
        stroke-width="2.6"
        stroke-linecap="round"
      />
      <path
        d="M33 15V30.5C33 32.4 31.4 34 29.5 34H18"
        stroke="url(#ostium-ring)"
        stroke-width="2.6"
        stroke-linecap="round"
        opacity=".6"
      />
      <circle
        cx="24"
        cy="24"
        r="4.2"
        fill="url(#ostium-core)"
        stroke="url(#ostium-ring)"
        stroke-width="1.4"
      />
      <circle cx="24" cy="24" r="1.6" fill="#5EEAD4" />
    </svg>
    <span v-if="wordmark" class="wordmark">Ostium</span>
  </div>
</template>

<style scoped>
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.wordmark {
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: var(--text);
}
</style>
