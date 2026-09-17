import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { useAvailableVariables } from '../../model/useAvailableVariables.js'
import {
  CODE_INPUT_TYPES,
  CODE_OUTPUT_TYPE_OPTIONS,
  normalizeCodeNodeData,
  removeCodeOutput,
  renameCodeOutput,
  setCodeErrorStrategy,
  syncCodeFunctionSignature,
  updateCodeDefaultValue,
  upsertCodeInput,
  upsertCodeOutput,
} from './codeNode.js'

export const OUTPUT_TYPE_OPTIONS = CODE_OUTPUT_TYPE_OPTIONS

export function useCodeConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const normalized = computed(() => normalizeCodeNodeData(nodeData.value || {}))
  const codeInputFilter = variable => CODE_INPUT_TYPES.has(variable?.type)
  const { flatOptions } = useAvailableVariables(() => props.nodeId, {
    filterVar: codeInputFilter,
  })

  const emitData = data => emit('update:nodeData', data)

  const codeLanguage = computed({
    get: () => normalized.value.code_language,
    set: code_language => emitData({ ...normalized.value, code_language }),
  })
  const code = computed({
    get: () => normalized.value.code,
    set: value => emitData({ ...normalized.value, code: value }),
  })
  const variables = computed(() => normalized.value.variables)
  const outputs = computed(() => normalized.value.outputs)

  function getSelectorType(selector) {
    const key = JSON.stringify(selector || [])
    return flatOptions.value.find(option => JSON.stringify(option.value) === key)?.type || 'string'
  }

  function handleAddInputVar(variable, value_selector) {
    if (variables.value.some(item => item.variable === variable))
      return false
    emitData(upsertCodeInput(normalized.value, variables.value.length, {
      variable,
      value_selector,
      value_type: getSelectorType(value_selector),
    }))
    return true
  }

  function handleRemoveInputVar(index) {
    emitData({
      ...normalized.value,
      variables: variables.value.filter((_, itemIndex) => itemIndex !== index),
    })
  }

  function handleUpdateInputVar(index, input) {
    emitData(upsertCodeInput(normalized.value, index, {
      ...input,
      value_type: getSelectorType(input.value_selector),
    }))
  }

  function handleAddOutputVar(name, type) {
    if (outputs.value[name])
      return false
    emitData(upsertCodeOutput(normalized.value, name, type || 'string'))
    return true
  }

  function handleRemoveOutputVar(name) {
    emitData(removeCodeOutput(normalized.value, name))
  }

  function handleRenameOutputVar(oldName, newName) {
    if (oldName !== newName && outputs.value[newName])
      return false
    emitData(renameCodeOutput(normalized.value, oldName, newName))
    return true
  }

  function handleUpdateOutputVarType(name, type) {
    emitData(upsertCodeOutput(normalized.value, name, type))
  }

  function handleSyncFunctionSignature() {
    emitData({
      ...normalized.value,
      code: syncCodeFunctionSignature(
        normalized.value.code,
        normalized.value.code_language,
        normalized.value.variables,
      ),
    })
  }

  function handleErrorStrategyUpdate(strategy) {
    emitData(setCodeErrorStrategy(normalized.value, strategy))
  }

  function handleDefaultValueUpdate({ key, value }) {
    emitData(updateCodeDefaultValue(normalized.value, key, value))
  }

  return {
    readOnly,
    codeLanguage,
    code,
    variables,
    outputs,
    OUTPUT_TYPE_OPTIONS,
    codeInputFilter,
    handleAddInputVar,
    handleRemoveInputVar,
    handleUpdateInputVar,
    handleAddOutputVar,
    handleRemoveOutputVar,
    handleRenameOutputVar,
    handleUpdateOutputVarType,
    handleSyncFunctionSignature,
    handleErrorStrategyUpdate,
    handleDefaultValueUpdate,
  }
}
