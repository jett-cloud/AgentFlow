// src/views/copilot/components/workflow/core/nodeProps.js
//
// VueFlow 节点组件使用 props.data；右侧 Panel 使用 props.nodeData。
// 配置 composable 统一通过此 helper 读取节点数据。

import { computed } from 'vue'

/** 从 Panel 或 VueFlow 节点 props 中解析节点 data */
export function getNodeData(props) {
  return props?.nodeData ?? props?.data ?? {}
}

/** 响应式版本，供 composable 使用 */
export function useResolvedNodeData(props) {
  return computed(() => getNodeData(props))
}
