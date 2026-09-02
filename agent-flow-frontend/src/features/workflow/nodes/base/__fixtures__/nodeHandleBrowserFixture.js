import { createPinia } from 'pinia'
import { ElIcon } from 'element-plus'
import { createApp, h, markRaw, ref } from 'vue'
import { VueFlow } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'

import NodeHandle from '../NodeHandle.vue'

const FixtureNode = {
  props: {
    id: { type: String, required: true },
    data: { type: Object, required: true },
    selected: { type: Boolean, default: false },
  },
  setup(props) {
    return () => h('div', {
      class: ['base-node', { 'is-selected': props.selected }],
      style: {
        position: 'relative',
        width: '240px',
        height: '80px',
        border: '1px solid #155eef',
        background: '#fff',
      },
    }, [
      props.data.withTarget
        ? h(NodeHandle, {
            nodeId: props.id,
            data: props.data,
            type: 'target',
            position: 'left',
            handleId: 'target',
          })
        : null,
      props.data.withSource
        ? h(NodeHandle, {
            nodeId: props.id,
            data: props.data,
            type: 'source',
            position: 'right',
            handleId: 'source',
          })
        : null,
    ])
  },
}

const nodes = ref([
  {
    id: 'source-node',
    type: 'fixture',
    position: { x: 80, y: 120 },
    data: { withSource: true },
    selected: true,
  },
  {
    id: 'target-node',
    type: 'fixture',
    position: { x: 480, y: 120 },
    data: { withTarget: true },
  },
])
const edges = ref([])
const selectorOpenCount = ref(0)

const app = createApp({
  setup() {
    const handleConnect = connection => {
      edges.value = [{ id: 'connected-edge', ...connection }]
    }

    return () => h('main', { style: { width: '800px', height: '400px' } }, [
      h(VueFlow, {
        nodes: nodes.value,
        edges: edges.value,
        nodeTypes: { fixture: markRaw(FixtureNode) },
        minZoom: 1,
        maxZoom: 1,
        defaultViewport: { x: 0, y: 0, zoom: 1 },
        onConnect: handleConnect,
      }),
      h('output', { id: 'edge-count' }, String(edges.value.length)),
      h('output', { id: 'selector-count' }, String(selectorOpenCount.value)),
    ])
  },
})

app.use(createPinia())
app.component('el-icon', ElIcon)
app.provide('workflowUi', {
  openNodeSelector() {
    selectorOpenCount.value += 1
  },
})
app.mount('#app')
