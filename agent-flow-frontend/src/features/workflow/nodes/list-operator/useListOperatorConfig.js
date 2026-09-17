// src/views/copilot/components/workflow/node/list-operator/useListOperatorConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { useAvailableVariables } from '../../model/useAvailableVariables.js'
import {
  createListFilterCondition,
  getListFilterOperators,
  isListVariableType,
  listOperatorRequiresConditionValue,
  normalizeListOperatorData,
  setListOperatorVariable,
  updateListOperatorSection,
} from './listOperator.js'

function selectorsEqual(left, right) {
  return JSON.stringify(left || []) === JSON.stringify(right || [])
}

export function useListOperatorConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const inputs = computed(() => normalizeListOperatorData(nodeData.value))
  const arrayTypeFilter = computed(() => variable => isListVariableType(variable?.type))
  const { flatOptions } = useAvailableVariables(
    () => props.nodeId,
    { filterVar: arrayTypeFilter },
  )

  function updateData(next) {
    emit('update:nodeData', next)
  }

  function updateSection(section, patch) {
    updateData(updateListOperatorSection(inputs.value, section, patch))
  }

  const variable = computed({
    get: () => inputs.value.variable,
    set: (selector) => {
      const option = flatOptions.value.find(item => selectorsEqual(item.value, selector))
      updateData(setListOperatorVariable(inputs.value, selector, option?.type || inputs.value.var_type))
    },
  })

  const filterEnabled = computed({
    get: () => !!inputs.value.filter_by.enabled,
    set: enabled => updateSection('filter_by', { enabled }),
  })
  const condition = computed(() => (
    inputs.value.filter_by.conditions[0]
    || createListFilterCondition(inputs.value.var_type)
  ))
  const filterKey = computed({
    get: () => condition.value.key || '',
    set: key => updateCondition({ key, comparison_operator: 'is', value: '' }),
  })
  const filterOperator = computed({
    get: () => condition.value.comparison_operator || '=',
    set: (comparison_operator) => {
      updateCondition({
        comparison_operator,
        ...(listOperatorRequiresConditionValue(comparison_operator) ? {} : { value: '' }),
      })
    },
  })
  const filterValue = computed({
    get: () => condition.value.value,
    set: value => updateCondition({ value }),
  })

  function updateCondition(patch) {
    updateSection('filter_by', {
      conditions: [{ ...condition.value, ...patch }],
    })
  }

  const extractEnabled = computed({
    get: () => !!inputs.value.extract_by.enabled,
    set: enabled => updateSection('extract_by', { enabled }),
  })
  const extractSerial = computed({
    get: () => inputs.value.extract_by.serial ?? '1',
    set: serial => updateSection('extract_by', { serial: String(serial ?? '') }),
  })
  const orderEnabled = computed({
    get: () => !!inputs.value.order_by.enabled,
    set: enabled => updateSection('order_by', {
      enabled,
      ...(enabled && inputs.value.var_type === 'arrayFile' && !inputs.value.order_by.key
        ? { key: 'name' }
        : {}),
    }),
  })
  const orderKey = computed({
    get: () => inputs.value.order_by.key || '',
    set: key => updateSection('order_by', { key }),
  })
  const orderDirection = computed({
    get: () => inputs.value.order_by.value || 'asc',
    set: value => updateSection('order_by', { value }),
  })
  const limitEnabled = computed({
    get: () => !!inputs.value.limit.enabled,
    set: enabled => updateSection('limit', { enabled }),
  })
  const limitSize = computed({
    get: () => inputs.value.limit.size ?? 10,
    set: size => updateSection('limit', { size: Number(size) }),
  })

  return {
    readOnly,
    inputs,
    variable,
    filterEnabled,
    filterKey,
    filterOperator,
    filterValue,
    filterOperators: computed(() => getListFilterOperators(inputs.value.item_var_type)),
    filterRequiresValue: computed(() => listOperatorRequiresConditionValue(filterOperator.value)),
    extractEnabled,
    extractSerial,
    orderEnabled,
    orderKey,
    orderDirection,
    limitEnabled,
    limitSize,
    legacyFilterCondition: computed(() => inputs.value.filter_condition || ''),
    hasFileSubVariables: computed(() => inputs.value.var_type === 'arrayFile'),
    itemType: computed(() => inputs.value.item_var_type || '?'),
    arrayTypeFilter: arrayTypeFilter.value,
  }
}
