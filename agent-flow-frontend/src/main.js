import { createApp } from 'vue'
import 'katex/dist/katex.min.css'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './shared/styles/theme.css'
import './features/workflow/styles/workflow-dialog.css'
import App from './app/App.vue'
import router from './app/router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
