// src/views/copilot/components/workflow/node/tool/useToolConfig.js
import { computed, watch } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { normalizeToolProviderType } from '@/features/integrations/state/toolCatalog.js'
import {
  buildEmptyToolParameters,
  setToolParamValue,
  toolParamDisplayValue,
  toToolParamInput,
} from '../../model/toolParamInputs.js'

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
    get: () => normalizeToolProviderType(nodeData.value?.provider_type || 'builtin'),
    set: (val) => patch({ provider_type: val }),
  })

  watch(
    () => nodeData.value?.provider_type,
    (type) => {
      if (readOnly.value)
        return
      const normalized = normalizeToolProviderType(type || 'builtin')
      if (type && type !== normalized)
        patch({ provider_type: normalized })
    },
    { immediate: true },
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

  function applyToolSelection(tool) {
    if (!tool) return
    const previous = toolParameters.value || {}
    const seeded = buildEmptyToolParameters(tool.parameters || [])
    for (const name of Object.keys(seeded)) {
      if (previous[name] !== undefined)
        seeded[name] = toToolParamInput(previous[name])
    }
    patch({
      provider_id: tool.provider_id,
      provider_type: tool.provider_type,
      provider_name: tool.provider_name,
      provider_icon: tool.icon ?? tool.icon_small ?? null,
      tool_name: tool.tool_name,
      tool_label: tool.tool_label,
      tool_parameters: seeded,
      tool_configurations: nodeData.value?.tool_configurations || {},
      tool_node_version: nodeData.value?.tool_node_version || '2',
      is_team_authorization: tool.is_team_authorization,
      title: tool.tool_label || tool.tool_name || nodeData.value?.title,
    })
  }

  function setParameter(name, value) {
    patch({
      tool_parameters: setToolParamValue(toolParameters.value, name, value),
    })
  }

  function parameterDisplayValue(name) {
    return toolParamDisplayValue(toolParameters.value?.[name])
  }

  return {
    readOnly,
    providerId,
    providerType,
    providerName,
    toolName,
    toolLabel,
    credentialId,
    toolParameters,
    toolConfigurations,
    applyToolSelection,
    setParameter,
    parameterDisplayValue,
  }
}
