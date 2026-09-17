import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { useAvailableVariables } from '../../model/useAvailableVariables.js'
import {
  TEMPLATE_TRANSFORM_INPUT_TYPES,
  addTemplateVariable,
  normalizeTemplateTransformData,
  removeTemplateVariable,
  renameTemplateVariable,
  updateTemplateVariable,
} from './templateTransform.js'

export function useTemplateTransformConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const normalized = computed(() => normalizeTemplateTransformData(nodeData.value || {}))
  const templateInputFilter = variable => TEMPLATE_TRANSFORM_INPUT_TYPES.has(variable?.type)
  const { flatOptions } = useAvailableVariables(() => props.nodeId, {
    filterVar: templateInputFilter,
  })

  const emitData = data => emit('update:nodeData', data)
  const template = computed({
    get: () => normalized.value.template,
    set: value => emitData({ ...normalized.value, template: value }),
  })
  const variables = computed(() => normalized.value.variables)

  function getSelectorType(selector) {
    const key = JSON.stringify(selector || [])
    return flatOptions.value.find(option => JSON.stringify(option.value) === key)?.type
  }

  function handleAddVar() {
    emitData(addTemplateVariable(normalized.value))
  }

  function handleUpdateVarName(index, name) {
    emitData(renameTemplateVariable(normalized.value, index, name))
  }

  function handleUpdateVarSelector(index, selector) {
    emitData(updateTemplateVariable(normalized.value, index, {
      value_selector: selector,
      value_type: getSelectorType(selector),
    }))
  }

  function handleRemoveVar(index) {
    emitData(removeTemplateVariable(normalized.value, index))
  }

  return {
    readOnly,
    template,
    variables,
    templateInputFilter,
    handleAddVar,
    handleUpdateVarName,
    handleUpdateVarSelector,
    handleRemoveVar,
  }
}
