// src/views/copilot/components/workflow/node/loop/useLoopConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { normalizeLoopData } from './loopNode.js'

export function useLoopConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const patch = partial => emit('update:nodeData', { ...normalizeLoopData(nodeData.value), ...partial })

  const maxIterations = computed({
    get: () => nodeData.value?.loop_count || nodeData.value?.max_iterations || 10,
    set: val => patch({ loop_count: val, max_iterations: undefined })
  })

  const loopVariables = computed(() => nodeData.value?.loop_variables || [])
  const breakConditions = computed(() => nodeData.value?.break_conditions || [])
  const logicalOperator = computed({
    get: () => nodeData.value?.logical_operator || 'and',
    set: val => patch({ logical_operator: val === 'or' ? 'or' : 'and' }),
  })

  function addLoopVariable() {
    patch({ loop_variables: [...loopVariables.value, { id: `loop-var-${Date.now()}`, label: '', var_type: 'string', value_type: 'constant', value: '' }] })
  }

  function updateLoopVariable(index, partial) {
    patch({ loop_variables: loopVariables.value.map((item, i) => i === index ? { ...item, ...partial } : item) })
  }

  function removeLoopVariable(index) {
    patch({ loop_variables: loopVariables.value.filter((_, i) => i !== index) })
  }

  function addBreakCondition() {
    patch({ break_conditions: [...breakConditions.value, { id: `loop-condition-${Date.now()}`, variable_selector: [], comparison_operator: '', value: '', varType: 'string' }] })
  }

  function updateBreakCondition(index, partial) {
    patch({ break_conditions: breakConditions.value.map((item, i) => i === index ? { ...item, ...partial } : item) })
  }

  function removeBreakCondition(index) {
    patch({ break_conditions: breakConditions.value.filter((_, i) => i !== index) })
  }

  return {
    readOnly,
    maxIterations,
    loopVariables,
    breakConditions,
    logicalOperator,
    addLoopVariable,
    updateLoopVariable,
    removeLoopVariable,
    addBreakCondition,
    updateBreakCondition,
    removeBreakCondition,
  }
}
