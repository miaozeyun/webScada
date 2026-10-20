import { createApp } from 'vue'
import { createPinia } from 'pinia'
// 按需引入（unplugin-vue-components 自动注入模板组件）：此处仅补 JS 调用类 API 与指令的样式
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/notification/style/css'
import 'element-plus/es/components/loading/style/css'

import App from './App.vue'
import router from './router'
import './styles/theme.css'
import { initTheme } from './utils/theme'

// 挂载前应用配色主题，避免首屏闪烁
initTheme()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
