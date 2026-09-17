// src/views/copilot/components/workflow/node/parameter-extractor/useParameterExtractorConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { normalizeParameterExtractorData } from './parameterExtractorNode.js'

export function useParameterExtractorConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)

  const parameters = computed(() => nodeData.value?.parameters || [])

  const updateData = (patch) => {
    emit('update:nodeData', normalizeParameterExtractorData({
      ...nodeData.value,
      ...patch,
    }))
  }

  const handleAddParam = (param) => {
    const list = [...parameters.value]
    list.push(param)
    updateData({ parameters: list })
  }

  const handleUpdateParam = (index, param) => {
    const list = [...parameters.value]
    list[index] = param
    updateData({ parameters: list })
  }

  const handleRemoveParam = (index) => {
    const list = [...parameters.value]
    list.splice(index, 1)
    updateData({ parameters: list })
  }

  return {
    readOnly,
    parameters,
    updateData,
    handleAddParam,
    handleUpdateParam,
    handleRemoveParam
  }
}
