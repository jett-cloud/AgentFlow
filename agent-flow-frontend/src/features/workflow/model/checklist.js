/**
 * Frontend checklist for workflow graphs (Dify-style pre-publish checks).
 * Flat issues keep level/message for tests; nodeId enables click-to-navigate.
 *
 * @param {{ nodes?: Array, edges?: Array }} graph
 * @param {{
 *   isChatMode?: boolean,
 *   environmentVariables?: Array,
 *   conversationVariables?: Array,
 *   ragPipelineVariables?: Array,
 * }} [options]
 * @returns {{ id: string, level: 'error' | 'warning', message: string, nodeId?: string | null, title?: string }[]}
 */
import {
  buildAvailableVariables,
  buildSpecialVarGroups,
  collectUsedSelectors,
  isSelectorAvailable,
} from './availableVariables.js'
import { listOperatorRequiresConditionValue } from '../nodes/list-operator/listOperator.js'
import {
  CODE_LANGUAGES,
  CODE_OUTPUT_TYPES,
  isValidCodeVariableName,
} from '../nodes/code/codeNode.js'
import { isValidTemplateVariableName } from '../nodes/template-transform/templateTransform.js'
import { isLoopConditionComplete } from '../nodes/loop/loopNode.js'
import { isIfElseConditionComplete } from '../nodes/if-else/ifElseNode.js'
import { isHumanInputDeliveryValid } from '../nodes/human-input/humanInputNode.js'
import { hasInvalidLLMJinjaMapping, isLLMPromptEmpty } from '../nodes/llm/llmNode.js'
import { hasInvalidParameterDefinitions } from '../nodes/parameter-extractor/parameterExtractorNode.js'
import {
  isKnowledgeMetadataValid,
  isKnowledgeMultipleConfigValid,
} from '../nodes/knowledge-retrieval/knowledgeRetrievalNode.js'
import { isKnowledgeRetrievalSettingValid } from '../nodes/knowledge-base/knowledgeBaseNode.js'
import { getDataSourceValidationErrors } from '../nodes/data-source/dataSourceNode.js'
import { getEndValidationErrors } from '../nodes/end/endNode.js'
import { getAnswerValidationErrors } from '../nodes/er/answerNode.js'
import { getLoopEndValidationErrors } from '../nodes/loop-end/loopEndNode.js'

export function buildWorkflowChecklist(graph = {}, options = {}) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : []
  const edges = Array.isArray(graph.edges) ? graph.edges : []
  const isChatMode = !!options.isChatMode
  const environmentVariables = options.environmentVariables || []
  const conversationVariables = options.conversationVariables || []
  const ragPipelineVariables = options.ragPipelineVariables || []
  const issues = []

  if (nodes.length === 0) {
    issues.push({ id: 'empty-graph', level: 'error', message: '画布为空，请至少添加开始节点与流程节点' })
    return issues
  }

  const startNodes = nodes.filter(node => node.data?.type === 'start' || node.type === 'start')
  const placeholders = nodes.filter(node => (node.data?.type || node.type) === 'start-placeholder')
  const entryTriggers = nodes.filter(node =>
    ['trigger-schedule', 'trigger-webhook', 'trigger-plugin', 'datasource'].includes(node.data?.type || node.type),
  )

  if (placeholders.length) {
    const ph = placeholders[0]
    issues.push({
      id: 'pick-start',
      level: 'error',
      message: '请先在右侧面板选择开始节点类型',
      nodeId: ph?.id || null,
      title: ph?.data?.title || '选择开始节点',
    })
  }
  else if (startNodes.length === 0 && entryTriggers.length === 0) {
    issues.push({ id: 'missing-start', level: 'error', message: '缺少开始节点' })
  }
  else if (startNodes.length > 1) {
    issues.push({ id: 'multi-start', level: 'error', message: '只能有一个开始节点' })
  }

  const endLike = nodes.filter(node => ['end', 'answer'].includes(node.data?.type || node.type))
  const answerNodes = nodes.filter(node => (node.data?.type || node.type) === 'answer')
  if (isChatMode && answerNodes.length === 0) {
    issues.push({
      id: 'answer-required',
      level: 'error',
      message: 'Chatflow 至少需要一个直接回复节点',
    })
  }
  else if (endLike.length === 0) {
    issues.push({ id: 'missing-end', level: 'warning', message: '建议添加结束节点或直接回复节点' })
  }

  const nodeIds = new Set(nodes.map(node => node.id))
  const incoming = new Set()
  const outgoing = new Set()
  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      issues.push({
        id: `dangling-edge-${edge.id || `${edge.source}-${edge.target}`}`,
        level: 'error',
        message: `存在无效连线：${edge.source} → ${edge.target}`,
      })
      continue
    }
    outgoing.add(edge.source)
    incoming.add(edge.target)
  }

  for (const node of nodes) {
    const type = node.data?.type || node.type
    if (['start', 'note', 'custom-note', 'iteration-start', 'loop-start', 'start-placeholder'].includes(type))
      continue
    if (!incoming.has(node.id) && !outgoing.has(node.id)) {
      issues.push({
        id: `orphan-${node.id}`,
        level: 'warning',
        message: `节点「${node.data?.title || node.id}」未连接到流程`,
        nodeId: node.id,
        title: node.data?.title || node.id,
      })
    }
  }

  const modelNodeTypes = new Set(['llm', 'question-classifier', 'parameter-extractor'])
  for (const node of nodes) {
    const type = node.data?.type || node.type
    const title = node.data?.title || node.id
    if (modelNodeTypes.has(type)) {
      const model = node.data?.model || {}
      const modelName = model.name || model.model
      if (!model.provider || !modelName) {
        issues.push({
          id: `model-config-${node.id}`,
          level: 'error',
          message: `节点「${title}」未配置模型提供商或模型，请先在工作区设置 API Key`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'http-request' && !String(node.data?.url || '').trim()) {
      issues.push({
        id: `http-url-${node.id}`,
        level: 'error',
        message: `HTTP 节点「${title}」未填写 URL`,
        nodeId: node.id,
        title,
      })
    }
    if (type === 'http-request' && node.data?.body?.type === 'binary') {
      const data = Array.isArray(node.data.body.data) ? node.data.body.data : []
      if (!data.some(item => item?.type === 'file' && Array.isArray(item.file) && item.file.length))
        issues.push({ id: `http-binary-${node.id}`, level: 'error', message: `HTTP 节点「${title}」的二进制请求体未选择文件`, nodeId: node.id, title })
    }
    if (type === 'tool' && (!node.data?.provider_id || !(node.data?.tool_name || node.data?.toolName))) {
      issues.push({
        id: `tool-${node.id}`,
        level: 'error',
        message: `工具节点「${title}」未选择工具`,
        nodeId: node.id,
        title,
      })
    }
    if (type === 'knowledge-retrieval' && !(node.data?.dataset_ids || []).length && !node.data?.dataset_id) {
      issues.push({
        id: `kr-${node.id}`,
        level: 'error',
        message: `知识检索「${title}」未选择知识库`,
        nodeId: node.id,
        title,
      })
    }
    if (type === 'datasource') {
      const errors = getDataSourceValidationErrors(node.data)
      if (errors.length) {
        issues.push({
          id: `datasource-${node.id}`,
          level: 'error',
          message: `数据源「${title}」配置无效：${errors.join('；')}`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'end') {
      const errors = getEndValidationErrors(node.data)
      if (errors.length) {
        issues.push({
          id: `end-outputs-${node.id}`,
          level: 'error',
          message: `结束节点「${title}」配置无效：${errors.join('；')}`,
          nodeId: node.id,
          title,
        })
      }
      if (isChatMode) {
        issues.push({
          id: `end-mode-${node.id}`,
          level: 'error',
          message: `结束节点「${title}」仅可用于 Workflow，请在 Chatflow 使用直接回复节点`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'knowledge-retrieval' && node.data?.retrieval_mode === 'single') {
      const model = node.data?.single_retrieval_config?.model || {}
      if (!model.provider || !(model.name || model.model)) {
        issues.push({ id: `kr-single-${node.id}`, level: 'error', message: `知识检索「${title}」的单路召回模型未配置`, nodeId: node.id, title })
      }
    }
    if (type === 'knowledge-retrieval' && !isKnowledgeMultipleConfigValid(node.data)) {
      issues.push({ id: `kr-multiple-${node.id}`, level: 'error', message: `知识检索「${title}」的 Top K、Score 或 Rerank 配置无效`, nodeId: node.id, title })
    }
    if (type === 'knowledge-retrieval' && !isKnowledgeMetadataValid(node.data)) {
      issues.push({ id: `kr-metadata-${node.id}`, level: 'error', message: `知识检索「${title}」的元数据过滤配置不完整`, nodeId: node.id, title })
    }
    if (type === 'knowledge-index') {
      if (!['text_model', 'hierarchical_model', 'qa_model'].includes(node.data?.chunk_structure)) {
        issues.push({ id: `kb-structure-${node.id}`, level: 'error', message: `知识库写入「${title}」未选择有效分段结构`, nodeId: node.id, title })
      }
      if (!Array.isArray(node.data?.index_chunk_variable_selector) || node.data.index_chunk_variable_selector.length < 2) {
        issues.push({ id: `kb-chunks-${node.id}`, level: 'error', message: `知识库写入「${title}」未选择分段输入变量`, nodeId: node.id, title })
      }
      if (!['high_quality', 'economy'].includes(node.data?.indexing_technique)) {
        issues.push({ id: `kb-index-${node.id}`, level: 'error', message: `知识库写入「${title}」未选择索引方式`, nodeId: node.id, title })
      }
      if (node.data?.indexing_technique === 'high_quality' && (!node.data?.embedding_model || !node.data?.embedding_model_provider)) {
        issues.push({ id: `kb-embedding-${node.id}`, level: 'error', message: `知识库写入「${title}」未配置 Embedding 模型`, nodeId: node.id, title })
      }
      const keywordNumber = Number(node.data?.keyword_number)
      if (!Number.isInteger(keywordNumber) || keywordNumber < 1 || keywordNumber > 100) {
        issues.push({ id: `kb-keyword-${node.id}`, level: 'error', message: `知识库写入「${title}」的关键词数量必须为 1 到 100`, nodeId: node.id, title })
      }
      if (!isKnowledgeRetrievalSettingValid(node.data)) {
        issues.push({ id: `kb-retrieval-${node.id}`, level: 'error', message: `知识库写入「${title}」的检索或 Rerank 配置无效`, nodeId: node.id, title })
      }
    }
    if (type === 'agent' || type === 'agent-v2') {
      const binding = node.data?.agent_binding || {}
      const isV2 = node.data?.agent_node_kind === 'dify_agent' && String(node.data?.version) === '2'
      const classicOk = Boolean(node.data?.agent_strategy_provider_name && node.data?.agent_strategy_name)
      let bindingOk = false
      if (binding.binding_type === 'roster_agent') {
        bindingOk = typeof binding.agent_id === 'string' && binding.agent_id.length > 0
      }
      else if (binding.binding_type === 'inline_agent' || isV2) {
        bindingOk = typeof binding.agent_id === 'string' && binding.agent_id.length > 0
          && typeof binding.current_snapshot_id === 'string' && binding.current_snapshot_id.length > 0
      }
      if (!bindingOk && !classicOk) {
        issues.push({
          id: `agent-${node.id}`,
          level: 'error',
          message: isV2 || binding.binding_type
            ? `Agent 节点「${title}」绑定未完成（inline 需 agent_id + snapshot，roster 需 agent_id）`
            : `Agent 节点「${title}」尚未完成绑定配置`,
          nodeId: node.id,
          title,
        })
      }
      // Inline agent-v2 needs a projected model on the graph (soul is in composer).
      if (isV2 && bindingOk && binding.binding_type === 'inline_agent') {
        const model = node.data?.model || {}
        const modelName = model.name || model.model
        if (!model.provider || !modelName) {
          issues.push({
            id: `agent-model-${node.id}`,
            level: 'error',
            message: `Agent 节点「${title}」未配置模型，请在侧栏选择模型并等待同步`,
            nodeId: node.id,
            title,
          })
        }
      }
    }
    if (type === 'code') {
      const variables = Array.isArray(node.data?.variables) ? node.data.variables : []
      const outputs = node.data?.outputs && typeof node.data.outputs === 'object'
        ? node.data.outputs
        : {}
      const inputNames = variables.map(item => String(item?.variable || ''))
      const outputEntries = Object.entries(outputs)

      if (!(String(node.data?.code || '').trim())) {
        issues.push({
          id: `code-${node.id}`,
          level: 'error',
          message: `代码节点「${title}」未填写代码`,
          nodeId: node.id,
          title,
        })
      }
      if (!CODE_LANGUAGES.includes(node.data?.code_language)) {
        issues.push({
          id: `code-language-${node.id}`,
          level: 'error',
          message: `代码节点「${title}」使用了不支持的语言`,
          nodeId: node.id,
          title,
        })
      }
      if (inputNames.some(name => !isValidCodeVariableName(name))) {
        issues.push({
          id: `code-input-name-${node.id}`,
          level: 'error',
          message: `代码节点「${title}」存在无效输入变量名`,
          nodeId: node.id,
          title,
        })
      }
      if (variables.some(item => !Array.isArray(item?.value_selector) || item.value_selector.length < 2)) {
        issues.push({
          id: `code-input-selector-${node.id}`,
          level: 'error',
          message: `代码节点「${title}」存在未选择上游值的输入变量`,
          nodeId: node.id,
          title,
        })
      }
      if (new Set(inputNames).size !== inputNames.length) {
        issues.push({
          id: `code-input-duplicate-${node.id}`,
          level: 'error',
          message: `代码节点「${title}」存在重复输入变量名`,
          nodeId: node.id,
          title,
        })
      }
      if (outputEntries.some(([name, output]) => (
        !isValidCodeVariableName(name) || !CODE_OUTPUT_TYPES.has(output?.type)
      ))) {
        issues.push({
          id: `code-output-${node.id}`,
          level: 'error',
          message: `代码节点「${title}」存在无效输出名称或类型`,
          nodeId: node.id,
          title,
        })
      }
      if (node.data?.error_strategy && !['default-value', 'fail-branch'].includes(node.data.error_strategy)) {
        issues.push({
          id: `code-error-strategy-${node.id}`,
          level: 'error',
          message: `代码节点「${title}」的异常处理策略无效`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'llm') {
      if (!node.data?.memory && isLLMPromptEmpty(node.data)) {
        issues.push({
          id: `llm-prompt-${node.id}`,
          level: 'error',
          message: `LLM 节点「${title}」未填写 Prompt`,
          nodeId: node.id,
          title,
        })
      }
      if (hasInvalidLLMJinjaMapping(node.data)) {
        issues.push({
          id: `llm-jinja-${node.id}`,
          level: 'error',
          message: `LLM 节点「${title}」存在未命名或未绑定的 Jinja 变量`,
          nodeId: node.id,
          title,
        })
      }
      if (node.data?.vision?.enabled && !node.data.vision?.configs?.variable_selector?.length) {
        issues.push({
          id: `llm-vision-${node.id}`,
          level: 'error',
          message: `LLM 节点「${title}」已开启视觉但未选择文件变量`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'parameter-extractor') {
      if (!Array.isArray(node.data?.query) || node.data.query.length < 2) {
        issues.push({
          id: `pe-query-${node.id}`,
          level: 'error',
          message: `参数提取节点「${title}」未选择输入文本变量`,
          nodeId: node.id,
          title,
        })
      }
      if (hasInvalidParameterDefinitions(node.data?.parameters)) {
        issues.push({
          id: `pe-parameters-${node.id}`,
          level: 'error',
          message: `参数提取节点「${title}」的参数名称、类型、描述或选项不完整`,
          nodeId: node.id,
          title,
        })
      }
      if (!['prompt', 'function_call'].includes(node.data?.reasoning_mode)) {
        issues.push({
          id: `pe-reasoning-${node.id}`,
          level: 'error',
          message: `参数提取节点「${title}」的推理模式无效`,
          nodeId: node.id,
          title,
        })
      }
      if (node.data?.vision?.enabled && !node.data.vision?.configs?.variable_selector?.length) {
        issues.push({
          id: `pe-vision-${node.id}`,
          level: 'error',
          message: `参数提取节点「${title}」已开启视觉但未选择文件变量`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'answer') {
      const errors = getAnswerValidationErrors(node.data)
      if (errors.length) {
        issues.push({
          id: `answer-${node.id}`,
          level: 'error',
          message: `直接回复「${title}」配置无效：${errors.join('；')}`,
          nodeId: node.id,
          title,
        })
      }
      if (!isChatMode) {
        issues.push({
          id: `answer-mode-${node.id}`,
          level: 'error',
          message: `直接回复「${title}」仅可用于 Chatflow，请在 Workflow 使用结束节点`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'if-else') {
      const caseList = Array.isArray(node.data?.cases) ? node.data.cases : []
      if (!caseList.length && !Array.isArray(node.data?.conditions)) {
        issues.push({
          id: `ifelse-${node.id}`,
          level: 'error',
          message: `条件分支「${title}」尚未配置分支条件`,
          nodeId: node.id,
          title,
        })
      }
      else if (caseList.length) {
        const emptyCase = caseList.some(c => !(c.conditions || []).length && c.case_id !== 'false')
        if (emptyCase) {
          issues.push({
            id: `ifelse-empty-${node.id}`,
            level: 'error',
            message: `条件分支「${title}」存在空条件分支`,
            nodeId: node.id,
            title,
          })
        }
        const incompleteCase = caseList.some(c => (c.conditions || []).some(condition => !isIfElseConditionComplete(condition)))
        if (incompleteCase)
          issues.push({ id: `ifelse-condition-${node.id}`, level: 'error', message: `条件分支「${title}」存在不完整条件`, nodeId: node.id, title })
      }
    }
    if (type === 'question-classifier') {
      const classes = node.data?.classes || node.data?.topics || []
      if (!Array.isArray(classes) || classes.length < 2) {
        issues.push({
          id: `qc-${node.id}`,
          level: 'warning',
          message: `问题分类「${title}」建议至少配置两个分类`,
          nodeId: node.id,
          title,
        })
      }
      if (!Array.isArray(node.data?.query_variable_selector) || !node.data.query_variable_selector.length)
        issues.push({ id: `qc-query-${node.id}`, level: 'error', message: `问题分类「${title}」未选择查询变量`, nodeId: node.id, title })
      if (Array.isArray(classes) && classes.some(item => !String(item?.name || '').trim()))
        issues.push({ id: `qc-classes-${node.id}`, level: 'error', message: `问题分类「${title}」存在未命名分类`, nodeId: node.id, title })
      if (node.data?.vision?.enabled && !node.data?.vision?.configs?.variable_selector?.length)
        issues.push({ id: `qc-vision-${node.id}`, level: 'error', message: `问题分类「${title}」已开启视觉但未选择图像变量`, nodeId: node.id, title })
    }
    if (type === 'human-input') {
      const deliveries = Array.isArray(node.data?.delivery_methods) ? node.data.delivery_methods : []
      const actions = Array.isArray(node.data?.user_actions) ? node.data.user_actions : []
      if (!deliveries.length || !deliveries.some(method => method?.enabled))
        issues.push({ id: `human-delivery-${node.id}`, level: 'error', message: `人工介入「${title}」未启用交付方式`, nodeId: node.id, title })
      if (deliveries.some(method => !isHumanInputDeliveryValid(method)))
        issues.push({ id: `human-email-${node.id}`, level: 'error', message: `人工介入「${title}」的邮件配置不完整`, nodeId: node.id, title })
      const actionIds = actions.map(action => String(action?.id || '').trim())
      if (!actions.length || actions.some(action => !String(action?.id || '').trim() || !String(action?.title || '').trim()) || new Set(actionIds).size !== actionIds.length)
        issues.push({ id: `human-actions-${node.id}`, level: 'error', message: `人工介入「${title}」的操作按钮配置无效`, nodeId: node.id, title })
      const timeout = Number(node.data?.timeout)
      if (!Number.isFinite(timeout) || timeout <= 0 || !['hour', 'day'].includes(node.data?.timeout_unit))
        issues.push({ id: `human-timeout-${node.id}`, level: 'error', message: `人工介入「${title}」的超时配置无效`, nodeId: node.id, title })
    }
    if (type === 'template-transform') {
      const templateVariables = Array.isArray(node.data?.variables) ? node.data.variables : []
      const variableNames = templateVariables.map(variable => String(variable?.variable || '').trim())
      if (!(String(node.data?.template || '').trim())) {
        issues.push({
          id: `template-${node.id}`,
          level: 'error',
          message: `模板转换「${title}」未填写模板`,
          nodeId: node.id,
          title,
        })
      }
      if (variableNames.some(name => !isValidTemplateVariableName(name))) {
        issues.push({
          id: `template-variable-name-${node.id}`,
          level: 'error',
          message: `模板转换「${title}」包含无效的变量名`,
          nodeId: node.id,
          title,
        })
      }
      if (new Set(variableNames.filter(Boolean)).size !== variableNames.filter(Boolean).length) {
        issues.push({
          id: `template-variable-duplicate-${node.id}`,
          level: 'error',
          message: `模板转换「${title}」包含重复的变量名`,
          nodeId: node.id,
          title,
        })
      }
      if (templateVariables.some(variable => !Array.isArray(variable?.value_selector) || !variable.value_selector.length)) {
        issues.push({
          id: `template-variable-value-${node.id}`,
          level: 'error',
          message: `模板转换「${title}」存在未绑定的输入变量`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'document-extractor') {
      const selector = node.data?.variable_selector
      if (!Array.isArray(selector) || !selector.length) {
        issues.push({
          id: `document-variable-${node.id}`,
          level: 'error',
          message: `文档提取器「${title}」未选择文件变量`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'iteration') {
      const selector = node.data?.iterator_selector
      if (!Array.isArray(selector) || !selector.length)
        issues.push({ id: `iteration-variable-${node.id}`, level: 'error', message: `迭代节点「${title}」未选择数组输入`, nodeId: node.id, title })
      if (node.data?.iterator_input_type && node.data.iterator_input_type !== 'array')
        issues.push({ id: `iteration-input-type-${node.id}`, level: 'error', message: `迭代节点「${title}」输入必须是数组`, nodeId: node.id, title })
      const parallel = Number(node.data?.parallel_nums ?? 10)
      if (!Number.isInteger(parallel) || parallel < 1 || parallel > 10)
        issues.push({ id: `iteration-parallel-${node.id}`, level: 'error', message: `迭代节点「${title}」并发数必须为 1 到 10`, nodeId: node.id, title })
    }
    if (type === 'loop') {
      const count = Number(node.data?.loop_count)
      if (!Number.isInteger(count) || count < 1 || count > 100)
        issues.push({ id: `loop-count-${node.id}`, level: 'error', message: `循环节点「${title}」的最大次数必须为 1 到 100`, nodeId: node.id, title })
      if ((node.data?.loop_variables || []).some(variable => !String(variable?.label || '').trim()))
        issues.push({ id: `loop-variable-${node.id}`, level: 'error', message: `循环节点「${title}」包含未命名循环变量`, nodeId: node.id, title })
      if ((node.data?.break_conditions || []).some(condition => !isLoopConditionComplete(condition)))
        issues.push({ id: `loop-condition-${node.id}`, level: 'error', message: `循环节点「${title}」包含不完整的退出条件`, nodeId: node.id, title })
    }
    if (type === 'loop-end') {
      const errors = getLoopEndValidationErrors(node, nodes)
      if (errors.length) {
        issues.push({
          id: `loop-end-${node.id}`,
          level: 'error',
          message: `退出循环节点「${title}」无效：${errors.join('；')}`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'assigner') {
      const items = node.data?.items || node.data?.variables || []
      if (!Array.isArray(items) || items.length === 0) {
        issues.push({
          id: `assigner-${node.id}`,
          level: 'warning',
          message: `变量赋值「${title}」尚未配置赋值项`,
          nodeId: node.id,
          title,
        })
      }
    }
    if (type === 'list-operator') {
      const variable = node.data?.variable || []
      if (!Array.isArray(variable) || variable.length === 0) {
        issues.push({
          id: `list-variable-${node.id}`,
          level: 'error',
          message: `列表操作「${title}」未选择输入数组`,
          nodeId: node.id,
          title,
        })
      }
      if (String(node.data?.filter_condition || '').trim()) {
        issues.push({
          id: `list-legacy-filter-${node.id}`,
          level: 'error',
          message: `列表操作「${title}」仍包含旧过滤表达式，请重新配置结构化过滤条件`,
          nodeId: node.id,
          title,
        })
      }
      const filterBy = node.data?.filter_by || {}
      const condition = filterBy.conditions?.[0]
      if (filterBy.enabled) {
        const missingFileKey = node.data?.var_type === 'arrayFile' && !condition?.key
        const missingOperator = !condition?.comparison_operator
        const needsValue = condition?.comparison_operator
          && listOperatorRequiresConditionValue(condition.comparison_operator)
        const missingValue = needsValue && (condition.value === '' || condition.value === undefined || condition.value === null)
        if (!condition || missingFileKey || missingOperator || missingValue) {
          issues.push({
            id: `list-filter-${node.id}`,
            level: 'error',
            message: `列表操作「${title}」的过滤条件不完整`,
            nodeId: node.id,
            title,
          })
        }
      }
      if (node.data?.extract_by?.enabled && !String(node.data.extract_by.serial ?? '').trim()) {
        issues.push({
          id: `list-extract-${node.id}`,
          level: 'error',
          message: `列表操作「${title}」未填写提取序号`,
          nodeId: node.id,
          title,
        })
      }
      if (node.data?.order_by?.enabled) {
        const invalidDirection = !['asc', 'desc'].includes(node.data.order_by.value)
        const missingFileKey = node.data?.var_type === 'arrayFile' && !node.data.order_by.key
        if (invalidDirection || missingFileKey) {
          issues.push({
            id: `list-order-${node.id}`,
            level: 'error',
            message: `列表操作「${title}」的排序配置不完整`,
            nodeId: node.id,
            title,
          })
        }
      }
      if (node.data?.limit?.enabled) {
        const size = Number(node.data.limit.size)
        if (!Number.isInteger(size) || size < 1 || size > 20) {
          issues.push({
            id: `list-limit-${node.id}`,
            level: 'error',
            message: `列表操作「${title}」的限制数量必须为 1 到 20 的整数`,
            nodeId: node.id,
            title,
          })
        }
      }
    }
  }

  // Contrasts Dify checklist invalidVariable: node-output refs must be upstream-available.
  // Special prefixes sys/env/conversation/rag are skipped (same as Dify isSpecialVar).
  const skipTypes = new Set([
    'start', 'note', 'custom-note', 'iteration-start', 'loop-start', 'start-placeholder',
  ])
  for (const node of nodes) {
    const type = node.data?.type || node.type
    if (skipTypes.has(type))
      continue
    const title = node.data?.title || node.id
    const used = collectUsedSelectors(node.data)
    if (!used.length)
      continue
    const availableGroups = [
      ...buildAvailableVariables({
        nodeId: node.id,
        nodes,
        edges,
        isChatMode,
        ragPipelineVariables,
      }),
      ...buildSpecialVarGroups({
        isChatMode,
        environmentVariables,
        conversationVariables,
        ragPipelineVariables,
      }),
    ]
    const invalid = used.find(selector => !isSelectorAvailable(selector, availableGroups))
    if (invalid) {
      issues.push({
        id: `invalid-var-${node.id}`,
        level: 'error',
        message: `节点「${title}」引用了不可用变量：${invalid.join('.')}`,
        nodeId: node.id,
        title,
      })
    }
  }

  return issues
}

/**
 * Group flat issues into Dify-like node cards for the checklist panel.
 * @param {ReturnType<typeof buildWorkflowChecklist>} issues
 * @returns {{ id: string, title: string, canNavigate: boolean, level: 'error' | 'warning', messages: string[] }[]}
 */
export function groupChecklistIssues(issues = []) {
  const groups = new Map()
  const global = []

  for (const issue of issues) {
    if (issue.nodeId) {
      const key = issue.nodeId
      if (!groups.has(key)) {
        groups.set(key, {
          id: key,
          title: issue.title || key,
          canNavigate: true,
          level: issue.level,
          messages: [],
        })
      }
      const group = groups.get(key)
      group.messages.push(issue.message)
      if (issue.level === 'error')
        group.level = 'error'
    }
    else {
      global.push({
        id: issue.id,
        title: issue.title || (issue.level === 'error' ? '全局错误' : '全局提示'),
        canNavigate: false,
        level: issue.level,
        messages: [issue.message],
      })
    }
  }

  return [...global, ...groups.values()]
}
