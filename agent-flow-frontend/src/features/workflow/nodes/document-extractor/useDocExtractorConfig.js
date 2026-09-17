import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { useAvailableVariables } from '../../model/useAvailableVariables.js'
import { isDocumentExtractorInput, setDocumentExtractorVariable } from './documentExtractor.js'

export function useDocExtractorConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const { flatOptions } = useAvailableVariables(() => props.nodeId, {
    filterVar: isDocumentExtractorInput,
  })
  const variableSelector = computed({
    get: () => nodeData.value?.variable_selector || [],
    set: selector => {
      const normalized = Array.isArray(selector) ? selector : []
      const selected = flatOptions.value.find(option => JSON.stringify(option.value) === JSON.stringify(normalized))
      emit('update:nodeData', setDocumentExtractorVariable(
        nodeData.value || {},
        normalized,
        selected?.type || '',
      ))
    },
  })
  const isArrayFile = computed(() => nodeData.value?.is_array_file === true)

  return {
    readOnly,
    variableSelector,
    isArrayFile,
    fileInputFilter: isDocumentExtractorInput,
    supportTypesShowNames: 'TXT, MARKDOWN, PDF, HTML, XLSX, DOCX, CSV, PPTX',
    helpLink: 'https://docs.dify.ai/v/zh-hans/guides/workflow/node/doc-extractor',
  }
}
