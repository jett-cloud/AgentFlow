// src/views/copilot/components/workflow/node/variable-aggregator/useVariableAggregatorConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'

export function useVariableAggregatorConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)

  const variables = computed(() => nodeData.value?.variables || [])

  const outputType = computed({
    get: () => nodeData.value?.output_type || 'any',
    set: (val) => emit('update:nodeData', { ...nodeData.value, output_type: val })
  })

  return {
    readOnly,
    variables,
    outputType
  }
}
