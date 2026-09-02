<template>
  <div class="start-placeholder-panel">
    <header class="spp-header">
      <div>
        <h2>选择开始节点</h2>
        <p>开始节点定义 workflow 的触发方式</p>
      </div>
      <button type="button" aria-label="关闭" @click="$emit('close')">×</button>
    </header>

    <div class="spp-search">
      <input v-model.trim="keyword" type="text" placeholder="搜索开始节点…" :disabled="readOnly" />
    </div>

    <div class="spp-list">
      <button
        v-for="item in filteredOptions"
        :key="item.type"
        type="button"
        class="spp-item"
        :disabled="readOnly"
        @click="selectStart(item.type)"
      >
        <BlockIcon :type="item.type" />
        <div class="spp-meta">
          <strong>{{ item.title }}</strong>
          <span>{{ item.desc }}</span>
        </div>
        <em v-if="item.badge">{{ item.badge }}</em>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, ref } from 'vue'
import BlockIcon from '../base/BlockIcon.vue'
import { START_BLOCK_OPTIONS } from '../../model/nodeMeta.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData', 'select-node'])

const workflowCore = inject('workflowCore', null)
const workflowUi = inject('workflowUi', null)
const keyword = ref('')

const filteredOptions = computed(() => {
  const kw = keyword.value.toLowerCase()
  if (!kw) return START_BLOCK_OPTIONS
  return START_BLOCK_OPTIONS.filter(item =>
    item.title.toLowerCase().includes(kw)
    || item.desc.toLowerCase().includes(kw)
    || item.type.includes(kw),
  )
})

async function selectStart(type) {
  if (props.readOnly) return
  const node = workflowCore?.replaceStartPlaceholder?.(props.nodeId, type)
  if (!node) return
  emit('select-node', node.id)
  await nextTick()
  workflowUi?.openNodeSelector?.({
    nodeId: node.id,
    sourceHandle: 'source',
    placeImmediately: true,
  })
}
</script>

<style scoped>
.start-placeholder-panel {
  display: flex;
  height: 100%;
  flex-direction: column;
  background: #fff;
}
.spp-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid #eaecf0;
}
.spp-header h2, .spp-header p { margin: 0; }
.spp-header h2 { font-size: 15px; color: #101828; }
.spp-header p { margin-top: 4px; font-size: 12px; color: #667085; }
.spp-header button {
  border: 0;
  border-radius: 6px;
  background: transparent;
  padding: 4px 8px;
  cursor: pointer;
  font-size: 16px;
}
.spp-header button:hover { background: #f2f4f7; }
.spp-search { padding: 10px 12px; border-bottom: 1px solid #f2f4f7; }
.spp-search input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  font-size: 13px;
}
.spp-list {
  flex: 1;
  overflow: auto;
  padding: 8px;
}
.spp-item {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  padding: 10px;
  margin-bottom: 4px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.spp-item:hover {
  border-color: #dbeafe;
  background: #f5f8ff;
}
.spp-item:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.spp-meta {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.spp-meta strong { font-size: 13px; color: #101828; }
.spp-meta span { font-size: 11px; color: #667085; line-height: 1.4; }
.spp-item em {
  flex-shrink: 0;
  padding: 2px 6px;
  border-radius: 999px;
  background: #eff4ff;
  color: #155eef;
  font-size: 10px;
  font-style: normal;
}
</style>
