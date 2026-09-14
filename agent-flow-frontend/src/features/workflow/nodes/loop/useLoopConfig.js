import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import {
  buildBreakConditionPatch,
  canonicalizeLoopVarType,
  coerceLoopConstant,
  createLoopEntityId,
  defaultLoopConstant,
  isLoopVariableSource,
  normalizeLoopData,
} from './loopNode.js'

export function useLoopConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const normalized = computed(() => normalizeLoopData(nodeData.value))
  const patch = partial => emit('update:nodeData', normalizeLoopData({ ...nodeData.value, ...partial }))

  const maxIterations = computed({
    get: () => normalized.value.loop_count,
    set: val => patch({ loop_count: val, max_iterations: undefined }),
  })

  const loopVariables = computed(() => normalized.value.loop_variables || [])
  const breakConditions = computed(() => normalized.value.break_conditions || [])
  const logicalOperator = computed({
    get: () => normalized.value.logical_operator || 'and',
    set: val => patch({ logical_operator: val === 'or' ? 'or' : 'and' }),
  })

  function addLoopVariable() {
    patch({
      loop_variables: [
        ...loopVariables.value,
        {
          id: createLoopEntityId(),
          label: '',
          var_type: 'string',
          value_type: 'constant',
          value: '',
        },
      ],
    })
  }

  function updateLoopVariable(index, partial) {
    patch({
      loop_variables: loopVariables.value.map((item, i) => (i === index ? { ...item, ...partial } : item)),
    })
  }

  function updateLoopVariableType(index, varType) {
    const variable = loopVariables.value[index]
    const nextType = canonicalizeLoopVarType(varType) || varType
    updateLoopVariable(index, {
      var_type: nextType,
      value: variable.value_type === 'variable' ? [] : defaultLoopConstant(nextType),
    })
  }

  function updateLoopVariableValueType(index, valueType) {
    const variable = loopVariables.value[index]
    updateLoopVariable(index, {
      value_type: valueType,
      value: valueType === 'variable' ? [] : defaultLoopConstant(variable.var_type),
    })
  }

  function updateLoopConstant(index, value) {
    updateLoopVariable(index, {
      value: coerceLoopConstant(loopVariables.value[index]?.var_type, value),
    })
  }

  function changeLoopVariableSource(index, selector, variable) {
    const varType = loopVariables.value[index]?.var_type
    if (variable && !isLoopVariableSource(variable, varType))
      return
    updateLoopVariable(index, { value: Array.isArray(selector) ? selector.map(String) : [] })
  }

  function removeLoopVariable(index) {
    patch({ loop_variables: loopVariables.value.filter((_, i) => i !== index) })
  }

  function addBreakCondition() {
    patch({
      break_conditions: [
        ...breakConditions.value,
        {
          id: createLoopEntityId(),
          variable_selector: [],
          comparison_operator: '',
          value: '',
          varType: 'string',
        },
      ],
    })
  }

  function updateBreakCondition(index, partial) {
    patch({
      break_conditions: breakConditions.value.map((item, i) => (i === index ? { ...item, ...partial } : item)),
    })
  }

  function changeBreakConditionSource(index, selector, variable) {
    updateBreakCondition(index, buildBreakConditionPatch(selector, variable || {}))
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
    updateLoopVariableType,
    updateLoopVariableValueType,
    updateLoopConstant,
    changeLoopVariableSource,
    removeLoopVariable,
    addBreakCondition,
    updateBreakCondition,
    changeBreakConditionSource,
    removeBreakCondition,
  }
}
