import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { createApp, h, nextTick, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

import WorkflowCanvas from '../WorkflowCanvas.vue'

import '@vue-flow/core/dist/style.css'
import 'element-plus/dist/index.css'
import '@/shared/styles/theme.css'

const canvas = ref(null)

const app = createApp({
  setup() {
    return () => h('main', { style: { width: '1000px', height: '700px' } }, [
      h(WorkflowCanvas, {
        ref: canvas,
        width: '1000px',
        height: '700px',
      }),
    ])
  },
})

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', component: { render: () => null } }],
})

app.use(createPinia())
app.use(router)
app.use(ElementPlus)
await router.push('/')
await router.isReady()
app.mount('#app')

await nextTick()
canvas.value.initFromGraph({
  nodes: [
    {
      id: 'start',
      position: { x: 482, y: 313 },
      data: { type: 'start', title: '开始', variables: [] },
    },
  ],
  edges: [],
  viewport: { x: 260, y: 140, zoom: 0.76 },
})
