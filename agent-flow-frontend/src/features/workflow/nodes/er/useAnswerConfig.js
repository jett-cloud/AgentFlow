// src/views/copilot/components/workflow/node/answer/useAnswerConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import {
  isAnswerVariableSupported,
  normalizeAnswerNodeData,
} from './answerNode.js'

/**
 * 直接回复节点 (Answer Node) 的配置状态与数据逻辑 Composable
 * 负责管理 Chatflow 模式下直接呈现在对话界面上的输出内容文本与插值变量模板 (answer)
 *
 * @param {Object} props - 组件传入的属性 (包含 nodeData, readOnly 等)
 * @param {Function} emit - 组件事件触发器 (用于触发 update:nodeData)
 */
export function useAnswerConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const normalized = computed(() => normalizeAnswerNodeData(nodeData.value || {}))

  // 响应式双向绑定当前节点的直接回复模版文本
  const answer = computed({
    get: () => normalized.value.answer,
    set: (val) => {
      emit('update:nodeData', {
        ...normalized.value,
        answer: val
      })
    }
  })

  return {
    readOnly,
    answer,
    answerVariableFilter: isAnswerVariableSupported,
  }
}
