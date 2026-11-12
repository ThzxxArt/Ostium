import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { i18n } from './locales'
import './styles/base.css'

const app = createApp(App)
app.use(createPinia())
app.use(i18n)
app.use(router)

app.config.errorHandler = (error, _instance, info) => {
  console.error('[ostium]', info, error)
}

router.isReady().then(() => app.mount('#app'))
