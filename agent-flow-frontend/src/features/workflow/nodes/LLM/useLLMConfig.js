// src/views/copilot/components/workflow/node/LLM/useLLMConfig.js
import { reactive, computed, ref } from 'vue'
import { useModelStore, ModelFeatureEnum } from '@/features/integrations/state/useModelStore.js'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { normalizeLLMNodeData } from './llmNode.js'

export const EditionType = {
  basic: 'basic',
  jinja2: 'jinja2',
}

function normalizePromptItem(item) {
  if (typeof item === 'string') {
    return { role: 'user', text: item, edition_type: EditionType.basic, jinja2_text: '' }
  }
  return {
    role: item?.role || 'user',
    text: item?.text || '',
    edition_type: item?.edition_type === EditionType.jinja2 ? EditionType.jinja2 : EditionType.basic,
    jinja2_text: item?.jinja2_text || '',
  }
}

/**
 * Vue 3 版本的 useLLMConfig 逻辑 Hook
 * 1:1 对标 Dify 官方源码: web/app/components/workflow/nodes/llm/use-config.ts
 */
export function useLLMConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const modelStore = useModelStore()

  // =========================================================================
  // 1. readOnly (只读模式判定)
  // 对应 Dify 源码: const { nodesReadOnly: readOnly } = useNodesReadOnly()
  // =========================================================================
  const readOnly = computed(() => Boolean(props.readOnly || nodeData.value?.readOnly))

  // =========================================================================
  // 2. inputs (节点全局响应式数据状态)
  // 对应 Dify 源码: const { inputs, setInputs } = useNodeCrud(id, payload)
  // =========================================================================
  const initial = normalizeLLMNodeData(nodeData.value || {})
  initial.prompt_template = (Array.isArray(initial.prompt_template)
    ? initial.prompt_template
    : [initial.prompt_template]).map(normalizePromptItem)
  initial.prompt_config = {
    ...(initial.prompt_config || {}),
    jinja2_variables: initial.prompt_config?.jinja2_variables || [],
  }
  initial.model.completion_params = {
    temperature: 0.7,
    top_p: 1,
    max_tokens: 2048,
    ...initial.model.completion_params,
  }
  const inputs = reactive(initial)
  const structuredSchemaDraft = ref(JSON.stringify(
    inputs.structured_output?.schema || {
      type: 'object',
      properties: {},
      required: [],
      additionalProperties: false,
    },
    null,
    2,
  ))

  // =========================================================================
  // 查表检索: 对应 Dify 源码 const { currentModel: currModel } = useTextGenerationCurrentProviderAndModelAndModelList(...)
  // =========================================================================
  const currModel = computed(() => {
    return modelStore.getModelSpec(inputs.model.name, inputs.model.provider)
  })

  // =========================================================================
  // 3. isChatModel (计算属性：是否为对话模型)
  // 对应 Dify 源码: const isChatModel = modelMode === AppModeEnum.CHAT
  // =========================================================================
  const isChatModel = computed(() => {
    return (currModel.value?.mode || inputs.model.mode) === 'chat'
  })

  // =========================================================================
  // 4. isChatMode (计算属性：应用是否为对话应用)
  // 对应 Dify 源码: const isChatMode = useIsChatMode()
  // =========================================================================
  const isChatMode = computed(() => props.appMode !== 'workflow')

  // =========================================================================
  // 5. shouldShowContextTip (计算属性：未在 Prompt 中引用 Context 变量时的警告提示)
  // 对应 Dify 源码: const shouldShowContextTip = !hasSetBlockStatus.context && inputs.context.enabled
  // =========================================================================
  const shouldShowContextTip = computed(() => {
    if (!inputs.context?.enabled) return false
    const promptStr = Array.isArray(inputs.prompt_template)
      ? inputs.prompt_template.map(p => `${p.text || ''}\n${p.jinja2_text || ''}`).join('')
      : String(inputs.prompt_template || '')
    return !promptStr.includes('{{') && !promptStr.includes('context')
  })

  const hasJinjaPrompt = computed(() =>
    Array.isArray(inputs.prompt_template)
    && inputs.prompt_template.some(item => item.edition_type === EditionType.jinja2),
  )

  // =========================================================================
  // 6. isVisionModel (计算属性：对应 Dify 源码: const isVisionModel = !!currModel?.features?.includes(ModelFeatureEnum.vision))
  // 查表检索当前选中的 currModel 对象的 features 特性数组中是否包含 'vision'
  // =========================================================================
  const isVisionModel = computed(() => {
    return Boolean(currModel.value?.features?.includes(ModelFeatureEnum.VISION))
  })

  // 通用更新与同步方法
  const notifyChange = () => {
    emit('update:nodeData', normalizeLLMNodeData({
      ...nodeData.value,
      ...inputs,
    }))
  }

  // =========================================================================
  // 7. handleModelChanged (模型切换句柄)
  // 对应 Dify 源码: const handleModelChanged = useCallback((model) => { ... })
  // =========================================================================
  const handleModelChanged = (newModel) => {
    if (typeof newModel === 'string') {
      const spec = modelStore.getModelSpec(newModel, inputs.model.provider)
      inputs.model.name = newModel
      if (spec) {
        inputs.model.provider = spec.provider
        inputs.model.mode = spec.mode
      }
    } else if (newModel && typeof newModel === 'object') {
      inputs.model.provider = newModel.provider || inputs.model.provider
      inputs.model.name = newModel.name || newModel.modelId || inputs.model.name
      if (newModel.mode) inputs.model.mode = newModel.mode
    }
    notifyChange()
  }

  // =========================================================================
  // 8. handleCompletionParamsChange (模型超参数修改句柄)
  // 对应 Dify 源码: const handleCompletionParamsChange = useCallback((newParams) => { ... })
  // =========================================================================
  const handleCompletionParamsChange = (newParams) => {
    if (newParams && typeof newParams === 'object') {
      Object.assign(inputs.model.completion_params, newParams)
      notifyChange()
    }
  }

  // =========================================================================
  // 9. handleContextVarChange (上下文引用变量改变句柄)
  // 对应 Dify 源码: const handleContextVarChange = useCallback((newVar) => { ... })
  // =========================================================================
  const handleContextVarChange = (newVar) => {
    inputs.context.variable_selector = newVar || []
    inputs.context.enabled = Boolean(newVar && newVar.length > 0)
    notifyChange()
  }

  // =========================================================================
  // 10. handlePromptChange (提示词模版改变句柄)
  // 对应 Dify 源码: const handlePromptChange = useCallback((newPayload) => { ... })
  // =========================================================================
  const handlePromptChange = (newPromptPayload) => {
    inputs.prompt_template = newPromptPayload
    notifyChange()
  }

  // =========================================================================
  // 11. handleMemoryChange (对话记忆滑动窗口改变句柄)
  // 对应 Dify 源码: const handleMemoryChange = useCallback((newMemory) => { ... })
  // =========================================================================
  const handleMemoryChange = (newMemoryConfig) => {
    if (typeof newMemoryConfig === 'boolean') {
      if (newMemoryConfig) {
        inputs.memory = {
          ...(inputs.memory || {}),
          window: { enabled: true, size: inputs.memory?.window?.size ?? 10 },
        }
      }
      else {
        delete inputs.memory
      }
    } else if (newMemoryConfig && typeof newMemoryConfig === 'object') {
      inputs.memory = { ...inputs.memory, ...newMemoryConfig }
    }
    notifyChange()
  }

  // =========================================================================
  // 12. handleVisionResolutionChange (视觉多模态分辨率及开关改变句柄)
  // 对应 Dify 源码: const handleVisionResolutionChange = useCallback((config) => { ... })
  // =========================================================================
  const handleVisionResolutionChange = (newVisionConfig) => {
    if (typeof newVisionConfig === 'boolean') {
      inputs.vision.enabled = newVisionConfig
      if (newVisionConfig) {
        inputs.vision.configs = {
          detail: inputs.vision.configs?.detail || 'high',
          variable_selector: inputs.vision.configs?.variable_selector || [],
        }
      }
    } else if (newVisionConfig && typeof newVisionConfig === 'object') {
      inputs.vision = { ...inputs.vision, ...newVisionConfig }
    }
    notifyChange()
  }

  // =========================================================================
  // 13. handleReasoningFormatChange (DeepSeek R1 / o1 推理链格式改变句柄)
  // 对应 Dify 源码: const handleReasoningFormatChange = useCallback((newFormat) => { ... })
  // =========================================================================
  const handleReasoningFormatChange = (newFormat) => {
    inputs.reasoning_format = newFormat
    notifyChange()
  }

  // =========================================================================
  // 14. handleStructureOutputChange (结构化 JSON 输出改变句柄)
  // 对应 Dify 源码: const handleStructureOutputChange = useCallback((newOutput) => { ... })
  // =========================================================================
  const handleStructureOutputChange = (newStructuredOutput) => {
    if (typeof newStructuredOutput === 'boolean') {
      inputs.structured_output_enabled = newStructuredOutput
    } else if (newStructuredOutput && typeof newStructuredOutput === 'object') {
      inputs.structured_output = { ...inputs.structured_output, ...newStructuredOutput }
    }
    notifyChange()
  }

  const memoryEnabled = computed({
    get: () => Boolean(inputs.memory?.window?.enabled),
    set: handleMemoryChange,
  })
  const memoryWindowSize = computed({
    get: () => inputs.memory?.window?.size ?? 10,
    set: (size) => handleMemoryChange({
      ...(inputs.memory || {}),
      window: { enabled: true, size },
    }),
  })
  const visionEnabled = computed({
    get: () => Boolean(inputs.vision?.enabled),
    set: handleVisionResolutionChange,
  })
  const visionDetail = computed({
    get: () => inputs.vision?.configs?.detail || 'high',
    set: detail => handleVisionResolutionChange({
      ...inputs.vision,
      enabled: true,
      configs: { ...(inputs.vision?.configs || {}), detail },
    }),
  })
  const structuredOutputSchemaText = computed({
    get: () => structuredSchemaDraft.value,
    set: (value) => {
      structuredSchemaDraft.value = value
      try {
        const schema = JSON.parse(value)
        handleStructureOutputChange({ schema })
      }
      catch {
        // Keep the editor draft until it becomes valid JSON.
      }
    },
  })

  return {
    readOnly,
    inputs,
    currModel,
    isChatModel,
    isChatMode,
    shouldShowContextTip,
    hasJinjaPrompt,
    isVisionModel,
    memoryEnabled,
    memoryWindowSize,
    visionEnabled,
    visionDetail,
    structuredOutputSchemaText,
    EditionType,
    handleModelChanged,
    handleCompletionParamsChange,
    handleContextVarChange,
    handlePromptChange,
    handleMemoryChange,
    handleVisionResolutionChange,
    handleReasoningFormatChange,
    handleStructureOutputChange,
    notifyChange
  }
}
