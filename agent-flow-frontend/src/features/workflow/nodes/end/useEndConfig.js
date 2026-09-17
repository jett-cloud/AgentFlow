import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { useAvailableVariables } from '../../model/useAvailableVariables.js'
import {
  normalizeEndNodeData,
  removeEndOutput,
  upsertEndOutput,
} from './endNode.js'

export function useEndConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const normalized = computed(() => normalizeEndNodeData(nodeData.value || {}))
  const outputs = computed(() => normalized.value.outputs)
  const { flatOptions } = useAvailableVariables(() => props.nodeId)

  function getSelectorType(selector) {
    const key = JSON.stringify(selector || [])
    return flatOptions.value.find(option => JSON.stringify(option.value) === key)?.type
  }

  function saveOutput(index, output) {
    const result = upsertEndOutput(normalized.value, index, {
      ...output,
      value_type: getSelectorType(output.value_selector) || output.value_type,
    })
    if (result.ok)
      emit('update:nodeData', result.data)
    return result.ok
  }

  function handleAddOutput(output) {
    return saveOutput(-1, output)
  }

  function handleUpdateOutput(index, output) {
    return saveOutput(index, output)
  }

  function handleRemoveOutput(index) {
    emit('update:nodeData', removeEndOutput(normalized.value, index))
  }

  return {
    readOnly,
    outputs,
    handleAddOutput,
    handleRemoveOutput,
    handleUpdateOutput,
  }
}
