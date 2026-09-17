// src/views/copilot/components/workflow/node/variable-assigner/useVariableAssignerConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { normalizeVariableAssignment } from './variableAssigner.js'

export function useVariableAssignerConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)

  const items = computed(() => (nodeData.value?.items || []).map(normalizeVariableAssignment))

  const handleAddItem = (item) => {
    const list = [...items.value]
    list.push(normalizeVariableAssignment(item))
    emit('update:nodeData', { ...nodeData.value, items: list })
  }

  const handleRemoveItem = (idx) => {
    const list = [...items.value]
    list.splice(idx, 1)
    emit('update:nodeData', { ...nodeData.value, items: list })
  }

  return {
    readOnly,
    items,
    handleAddItem,
    handleRemoveItem
  }
}
