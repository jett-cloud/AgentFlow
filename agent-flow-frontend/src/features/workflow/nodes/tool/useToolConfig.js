import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { normalizeToolProviderType } from '@/features/integrations/state/toolCatalog.js'
import {
  setToolParamValue,
  toolParamDisplayValue,
} from '../../model/toolParamInputs.js'
import {
  applyToolParamUpdate,
  applyToolSelection as applyToolSelectionData,
  setToolErrorStrategy,
  updateToolDefaultValue,
} from './toolNode.js'

export function useToolConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)

  function patch(partial) {
    emit('update:nodeData', { ...nodeData.value, ...partial })
  }

  const providerId = computed({
    get: () => nodeData.value?.provider_id || '',
    set: (val) => patch({ provider_id: val }),
  })

  const providerType = computed({
    get: () => nodeData.value?.provider_type || 'builtin',
    set: (val) => patch({ provider_type: val }),
  })

  const catalogueProviderType = computed(() =>
    normalizeToolProviderType(providerType.value || 'builtin'),
  )

  const providerName = computed({
    get: () => nodeData.value?.provider_name || '',
    set: (val) => patch({ provider_name: val }),
  })

  const toolName = computed({
    get: () => nodeData.value?.tool_name || '',
    set: (val) => patch({ tool_name: val }),
  })

  const toolLabel = computed({
    get: () => nodeData.value?.tool_label || nodeData.value?.tool_name || '',
    set: (val) => patch({ tool_label: val }),
  })

  const credentialId = computed({
    get: () => nodeData.value?.credential_id || '',
    set: (val) => patch({ credential_id: val }),
  })

  const toolParameters = computed({
    get: () => nodeData.value?.tool_parameters || {},
    set: (val) => patch({ tool_parameters: val }),
  })

  const toolConfigurations = computed({
    get: () => nodeData.value?.tool_configurations || {},
    set: (val) => patch({ tool_configurations: val }),
  })

  function paramSchema(name) {
    return (nodeData.value?.parameters || []).find(item => item?.name === name) || { name, form: 'llm' }
  }

  function applyToolSelection(tool) {
    if (!tool)
      return
    emit('update:nodeData', applyToolSelectionData(nodeData.value, tool))
  }

  function setParameter(name, value) {
    const params = setToolParamValue(toolParameters.value, name, value)
    emit('update:nodeData', applyToolParamUpdate(nodeData.value, paramSchema(name), params[name]))
  }

  function setParameterEnvelope(name, envelope) {
    emit('update:nodeData', applyToolParamUpdate(nodeData.value, paramSchema(name), envelope))
  }

  function parameterDisplayValue(name) {
    return toolParamDisplayValue(toolParameters.value?.[name])
  }

  function parameterValue(name) {
    return toolParameters.value?.[name]?.value
  }

  function handleRetryConfigUpdate(retryConfig) {
    patch({ retry_config: retryConfig })
  }

  function handleErrorStrategyUpdate(strategy) {
    emit('update:nodeData', setToolErrorStrategy(nodeData.value, strategy))
  }

  function handleDefaultValueUpdate({ key, value }) {
    emit('update:nodeData', updateToolDefaultValue(nodeData.value, key, value))
  }

  return {
    readOnly,
    providerId,
    providerType,
    catalogueProviderType,
    providerName,
    toolName,
    toolLabel,
    credentialId,
    toolParameters,
    toolConfigurations,
    applyToolSelection,
    setParameter,
    setParameterEnvelope,
    parameterDisplayValue,
    parameterValue,
    handleRetryConfigUpdate,
    handleErrorStrategyUpdate,
    handleDefaultValueUpdate,
  }
}
