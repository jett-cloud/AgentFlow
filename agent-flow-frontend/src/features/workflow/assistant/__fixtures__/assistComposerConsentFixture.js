import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { createApp, h, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useWorkflowAssistStore } from '@/stores/useWorkflowAssistStore.js'
import AssistComposer from '../AssistComposer.vue'

const disabled = ref(false)

const app = createApp({
  setup() {
    const assistStore = useWorkflowAssistStore()
    return () => h('main', [
      h(AssistComposer, {
        disabled: disabled.value,
        language: 'en',
        modelValue: { provider: '', name: '', mode: 'chat', completion_params: {} },
        currentGraph: { nodes: [], edges: [] },
        executionConsentMode: assistStore.executionConsentMode,
        'onUpdate:executionConsentMode': assistStore.setExecutionConsentMode,
      }),
      h('output', { id: 'stored-consent-mode' }, assistStore.executionConsentMode),
      h('button', { id: 'disable-composer', onClick: () => { disabled.value = true } }, 'Disable'),
    ])
  },
})

app.use(createPinia())
app.use(ElementPlus)
app.use(createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', component: { render: () => h('div') } }],
}))
app.mount('#app')
