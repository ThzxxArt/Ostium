<script setup lang="ts">
import DashboardPage from './DashboardPage.vue'
import ClientHomePage from './ClientHomePage.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
</script>

<template>
  <component :is="auth.isServer ? DashboardPage : ClientHomePage" />
</template>
