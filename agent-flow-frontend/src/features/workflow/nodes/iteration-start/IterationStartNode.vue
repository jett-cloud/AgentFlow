<!-- src/views/copilot/components/workflow/node/iteration-start/IterationStartNode.vue -->
<!--
  迭代起点节点 (IterationStartNode)
  1:1 对齐 Dify React 官方源码 (web/app/components/workflow/nodes/iteration-start/index.tsx)
-->
<template>
  <div class="iteration-start-node nodrag" title="迭代起点 (Iteration Start)">
    <!-- 内部起点圈 -->
    <div class="start-icon-circle">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="12" height="12" fill="currentColor">
        <path d="M19 21H5a1 1 0 0 1-1-1v-9H1l10.327-9.388a1 1 0 0 1 1.346 0L23 11h-3v9a1 1 0 0 1-1 1zm-6-2h4v-7h-4v7z" />
      </svg>
    </div>

    <!-- 右侧输出 Handle 锚点 (允许从迭代起点拖拽连线至其他子节点) -->
    <NodeHandle :node-id="id" :data="data" type="source" position="right" handle-id="source" centered />
  </div>
</template>

<script setup>
import NodeHandle from '../base/NodeHandle.vue'

defineProps({
  id: { type: String, required: true },
  data: { type: Object, default: () => ({}) },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false }
})
</script>

<style scoped>
.iteration-start-node {
  position: relative;
  width: 44px;
  height: 44px;
  border-radius: 16px;
  border: 1px solid #eaecf0;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
  user-select: none;
  z-index: 10;
}

.start-icon-circle {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #155eef;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2);
}

</style>
