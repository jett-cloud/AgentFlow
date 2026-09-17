const COPY = {
  en: {
    liveAcceptanceTitle: 'Authorize a live trial',
    liveAcceptanceNotice: 'This trial uses real models, agents and the configured tools listed below. Provider charges and external writes may occur. Agent calls include its configured tools and MCP capabilities. Approval applies only to this candidate version and one execution.',
    liveAcceptanceEffects: 'May change external data',
    liveAcceptanceApprove: 'Authorize one live trial',
    liveAcceptanceSimulate: 'Use simulated checks only',
    liveAcceptanceBudget: request => `One execution, up to ${request.max_steps} workflow steps and a ${request.max_seconds}s engine time limit. In-flight provider requests may finish later. Nested agent calls use their configured limits; this is not a price guarantee.`,
    title: 'Workflow Agent',
    workflowSubtitle: 'Workflow assistant',
    chatflowSubtitle: 'Chatflow assistant',
    resize: 'Resize Workflow Agent panel',
    newConversation: 'New conversation',
    history: 'Conversation history',
    deleteConversation: 'Delete conversation',
    confirmDeleteConversation: 'Delete this conversation? The candidate graph is discarded; the saved draft is unchanged.',
    renameConversation: 'Rename conversation',
    candidatePreviewNotice: 'Previewing this conversation’s candidate. Apply to save it as the draft. Closing the assistant keeps this preview.',
    restoreDraft: 'Restore draft',
    close: 'Close Workflow Agent',
    loading: 'Loading…',
    restoringHistory: 'Restoring conversation history and run status. Sending is temporarily disabled.',
    historyRecoveryFailed: 'History could not be restored. Retry loading or explicitly start a new conversation.',
    retryHistory: 'Retry loading history',
    authenticationRequired: 'The live connection needs a new login. This does not mean the task failed; sign in again to restore its status and messages.',
    signInAgain: 'Sign in again',
    untitledConversation: 'Untitled conversation',
    noConversations: 'No conversations yet',
    emptyTitle: 'Describe how you want to change the workflow',
    emptyHint: 'Messages and clarification questions stay in one recoverable conversation. You decide when to apply the candidate.',
    instructionLabel: 'Workflow change instruction',
    instructionPlaceholder: 'For example: add an Agent that uses a tool to complete the task',
    selectModel: 'Select model',
    send: 'Send',
    sendInstruction: 'Send instruction',
    sendAnswer: 'Send answer or follow-up',
    stop: 'Stop',
    stopTitle: 'Stop this Run',
    modelRequired: 'Select a model before sending.',
    waitingHint: 'Your answer creates a new Turn and keeps the completed clarification Run in history.',
    localEdit: 'Local edit',
    removeTarget: 'Remove target node',
    mentionNodes: 'Nodes',
    mentionTools: 'Tools',
    mentionDatasets: 'Knowledge',
    mentionEmpty: 'No matches',
    mentionMenu: 'Mention resources',
    applyReady: 'The server-owned candidate is complete and ready to apply.',
    apply: 'Apply changes',
    applying: 'Applying…',
    applyConflict: 'The draft or active Run changed. Server facts were refreshed; review and try again.',
    applyFailed: 'Unable to apply the candidate. Review the error and try again.',
    retry: 'Retry',
    retryThisStep: 'Retry this step',
    shortenRequirement: 'Shorten requirement',
    switchModel: 'Switch model',
    rawError: 'View raw error',
    answer: 'Answer',
    answerPlaceholder: 'Type your answer',
    statusFailed: 'This Run did not complete',
    statusCompleted: 'Operations completed',
    statusWorking: 'Working…',
    statusRunQueued: 'Run queued.',
    statusRunRunning: 'Run in progress.',
    statusRunWaitingUser: 'Run needs your answer.',
    statusRunDone: 'Run completed.',
    statusRunFailed: 'Run failed.',
    statusRunError: 'Run encountered an error.',
    statusRunAborted: 'Run stopped.',
    statusRunTurnComplete: 'Waiting for your next message.',
    statusApplyReady: 'Candidate ready to apply.',
    statusApplyApplying: 'Applying candidate…',
    statusApplyApplied: 'Candidate applied.',
    statusApplyConflict: 'Apply facts changed; candidate refreshed.',
    statusApplyFailed: 'Candidate could not be applied.',
    validationPassed: 'Validation passed',
    changed: 'Changed',
    globalError: 'Workflow Assist could not complete the request.',
    defaultError: 'Request failed. Try again later.',
    errorRules: {
      emptyModelResponse: 'The model returned no content, possibly because reasoning used the output budget. Switch models or shorten the request and try again.',
      noJsonObject: 'The model did not return the plan as JSON. Try again or switch to a model that handles structured output better.',
      outputTruncated: 'The response exceeded this model\'s output limit and the plan was truncated. Split the request into smaller parts or switch to a model with a larger output limit.',
      missingPlan: 'Planning finished without a plan result. Try again.',
    },
    errorCodes: {
      provider_error: 'The model provider could not complete this request. Try again or switch models.',
      PLANNER_CONTEXT_LIMIT: 'The planning context exceeds this model\'s limit. Shorten the request or switch to a model with a larger context window.',
      PLANNER_ACTION_LIMIT: 'The planner reached this Run\'s action limit. Try again or split the request into smaller steps.',
      PLANNER_NO_PROGRESS: 'The planner repeated the same operation without progress. Try again or add clearer constraints.',
      PLANNER_MISSING_PLAN: 'Planning finished without a plan result. Try again.',
      PLANNER_REQUIREMENT_INVALID: 'The request could not be validated. Rephrase it or add clearer constraints and try again.',
      PLANNER_BUDGET_EXHAUSTED: 'The planning budget is exhausted. Reload this conversation or start the request as a new task.',
      PLANNER_POLICY_DENIED: 'The planning action was denied by the safety policy. Try again so the Agent can choose another action.',
      PLANNER_CLARIFICATION_LIMIT: 'This plan reached its clarification limit. Add the complete constraints and send them as a new request.',
      PLANNING_SESSION_CONFLICT: 'A newer message is available. Reload the latest conversation before continuing.',
      OUTPUT_TRUNCATED: 'The model output was truncated. Shorten the request or switch to a model with a larger output limit.',
      CLARIFICATION_ALREADY_RESOLVED: 'These clarification questions were already handled. Restoring the latest conversation state.',
      CLARIFICATION_EXPIRED: 'These clarification questions expired. Restoring the latest questions.',
      CLARIFICATION_NOT_FOUND: 'These clarification questions are no longer valid. Restoring the latest questions.',
      INVALID_CLARIFICATION_ID: 'These clarification questions are no longer valid. Restoring the latest questions.',
      UNKNOWN_TOOL: 'The selected tool is unavailable. Plan again or select another tool.',
      UNKNOWN_DATASET: 'The selected knowledge base is unavailable. Plan again or select another knowledge base.',
      CANDIDATE_BASE_STALE: 'The canvas changed, so the candidate is based on an older version',
    },
    planning: 'Planning…',
    generatingWorkflow: 'Generating workflow…',
    processing: 'Processing…',
    resolvingResources: 'Resolving resources…',
    understandingRequirements: 'Understanding the request…',
    generatingStructure: 'Generating structure…',
    waitingForInformation: 'Waiting for more information…',
    understoodRequirements: 'Understood {count} requirements{suffix}',
    understoodCurrentRequest: 'Understood the current request',
    resolvingResource: 'Resolving {resource} resources…',
    boundResource: 'Bound {resource}: {name}',
    availableResource: 'available resource',
    requirementLabelsSeparator: ', ',
    requirementLabelsPrefix: ': ',
    resourceLabels: {
      dataset: 'knowledge base',
      tool: 'tool',
      resource: 'resource',
    },
    quoteLeft: '"',
    quoteRight: '"',
    activityFailurePrefix: 'Failed: ',
    activitySummarySeparator: ' · ',
    thinking: 'Thinking…',
    thought: 'Thought',
    other: 'Other',
    submitAnswers: 'Submit answers',
    chooseOne: 'Choose one',
    chooseMultiple: 'Choose any that apply',
    answerPlaceholder: 'Enter your answer',
    otherPlaceholder: 'Or type your own answer',
    toolLabels: {
      build_node: 'Write node',
      validate_graph: 'Validate',
      search_datasets: 'Search knowledge bases',
      search_tools: 'Search tools',
      list_models: 'List available models',
      read_graph: 'Read structure',
      read_node: 'Read node',
      connect: 'Connect',
      disconnect: 'Disconnect',
      delete_node: 'Delete node',
      inspect_node_schema: 'Inspect fields',
      finish: 'Finish validation',
      ask_user: 'Ask',
      fail: 'Failed',
    },
    abortStatuses: {
      superseded_by_new_turn: 'The previous Run stopped for your new message; its saved candidate is preserved.',
      user_abort: 'Stopped.',
      transport_disconnect: 'Connection interrupted; the saved candidate is preserved.',
    },
    staleApplyNotice: 'The canvas changed, so the candidate is based on an older version. Continue the conversation to update it from the current canvas.',
    contractValidationTitle: 'Contract reconciliation',
    contractValidationSummary: '{satisfied} passed · {missing} missing · {conflict} conflicts · {unverified} unverified',
    contractValidationLevels: {
      verified: 'Statically verified',
      partially_verified: 'Static checks passed; effects unverified',
      blocked: 'Blocked',
      unavailable: 'Unavailable',
    },
    contractValidationCategories: {
      node: 'Node',
      input: 'Variable input',
      output: 'Variable output',
      final_output: 'Final output',
      edge: 'Connection',
      resource: 'Resource',
      edit_scope: 'Edit scope',
      contract: 'Contract',
      graph: 'Graph',
      requirement: 'Acceptance check',
    },
  },
  'zh-Hans': {
    liveAcceptanceTitle: '授权真实试运行',
    liveAcceptanceNotice: '本次将调用下列真实模型、Agent 和已配置工具，可能产生费用或修改外部数据。Agent 调用包含其配置的工具和 MCP 能力。授权仅适用于当前候选图版本的一次执行。',
    liveAcceptanceEffects: '可能修改外部数据',
    liveAcceptanceApprove: '授权一次真实试运行',
    liveAcceptanceSimulate: '仅做模拟检查',
    liveAcceptanceBudget: request => `限一次执行，最多 ${request.max_steps} 个工作流步骤，引擎时限 ${request.max_seconds} 秒。已发出的请求可能稍后才结束；Agent 内部调用遵循其配置上限，此限制不保证具体费用。`,
    title: '工作流 Agent',
    workflowSubtitle: 'Workflow 助手',
    chatflowSubtitle: 'Chatflow 助手',
    resize: '调整工作流 Agent 面板宽度',
    newConversation: '新建会话',
    history: '历史会话',
    deleteConversation: '删除会话',
    confirmDeleteConversation: '删除这个会话？候选图会丢弃，已保存的草稿不会改动。',
    renameConversation: '重命名会话',
    candidatePreviewNotice: '正在预览该会话的候选工作流。点「应用」才会写入草稿；关闭助手后预览仍保留。',
    restoreDraft: '恢复草稿',
    close: '关闭工作流 Agent',
    loading: '加载中…',
    restoringHistory: '正在恢复历史对话和运行状态，暂时不能发送消息。',
    historyRecoveryFailed: '历史对话恢复失败，请重试加载，或主动新建对话。',
    retryHistory: '重新加载历史',
    authenticationRequired: '实时连接的登录凭证已失效，不代表任务执行失败。请重新登录，恢复原任务的状态和消息。',
    signInAgain: '重新登录',
    untitledConversation: '未命名会话',
    noConversations: '还没有历史会话',
    emptyTitle: '描述你想如何调整工作流',
    emptyHint: '消息和澄清问题会保留在同一个可恢复会话中，最后由你决定是否应用候选图。',
    instructionLabel: '工作流修改指令',
    instructionPlaceholder: '例如：添加一个使用工具完成任务的 Agent',
    selectModel: '选择模型',
    send: '发送',
    sendInstruction: '发送指令',
    sendAnswer: '发送回答或追问',
    stop: '停止',
    stopTitle: '停止当前 Run',
    modelRequired: '请先选择模型后再发送。',
    waitingHint: '回答会创建新的 Turn，已结束的澄清 Run 会保留在历史中。',
    localEdit: '局部编辑',
    removeTarget: '移除目标节点',
    mentionNodes: '节点',
    mentionTools: '工具',
    mentionDatasets: '知识库',
    mentionEmpty: '没有匹配项',
    mentionMenu: '引用资源',
    applyReady: '服务端候选图已完成，可以应用到草稿。',
    apply: '应用变更',
    applying: '应用中…',
    applyConflict: '草稿或活动 Run 已变化，已刷新服务端事实，请确认后重试。',
    applyFailed: '候选图应用失败，请检查错误后重试。',
    retry: '重试',
    retryThisStep: '重试此步',
    shortenRequirement: '缩短需求',
    switchModel: '切换模型',
    rawError: '查看原始错误',
    answer: '回答',
    answerPlaceholder: '输入你的回答',
    statusFailed: '本轮操作未完成',
    statusCompleted: '已完成操作',
    statusWorking: '正在处理…',
    statusRunQueued: 'Run 已排队。',
    statusRunRunning: 'Run 正在执行。',
    statusRunWaitingUser: 'Run 正在等待你的回答。',
    statusRunDone: 'Run 已完成。',
    statusRunFailed: 'Run 执行失败。',
    statusRunError: 'Run 执行时出现错误。',
    statusRunAborted: 'Run 已停止。',
    statusRunTurnComplete: '等待你的下一条消息。',
    statusApplyReady: '候选图已可应用。',
    statusApplyApplying: '正在应用候选图…',
    statusApplyApplied: '候选图已应用。',
    statusApplyConflict: '应用事实已变化，候选图已刷新。',
    statusApplyFailed: '候选图未能应用。',
    validationPassed: '校验通过',
    changed: '变更',
    globalError: 'Workflow Assist 未能完成请求。',
    defaultError: '请求失败，请稍后重试。',
    errorRules: {
      emptyModelResponse: '模型没有返回任何内容，可能是推理占满了输出预算。可以换一个模型，或把需求拆短后重试。',
      noJsonObject: '模型没有按 JSON 格式返回规划结果。可以直接重试，或换一个更擅长结构化输出的模型。',
      outputTruncated: '输出超出了该模型的输出长度上限，计划被截断。请把需求拆成几段分别生成，或换一个支持更长输出的模型。',
      missingPlan: '规划已结束但没有收到计划结果，请重试。',
    },
    errorCodes: {
      provider_error: '模型服务未能完成请求，请重试或切换模型。',
      PLANNER_CONTEXT_LIMIT: '规划上下文已超过当前模型上限。请缩短需求，或切换到上下文更长的模型。',
      PLANNER_ACTION_LIMIT: '规划器已达到本轮动作上限。可以重试，或把需求拆成更小的步骤。',
      PLANNER_NO_PROGRESS: '规划器连续执行了相同操作，没有取得新进展。请重试或补充更明确的约束。',
      PLANNER_MISSING_PLAN: '规划已结束但没有收到计划结果，请重试。',
      PLANNER_REQUIREMENT_INVALID: '本轮需求理解未通过校验。请换一种说法或补充更明确的约束后重试。',
      PLANNER_BUDGET_EXHAUSTED: '规划预算已耗尽。请重新载入当前会话，或把需求作为新任务开始。',
      PLANNER_POLICY_DENIED: '规划动作被安全策略拒绝。可以重试，让 Agent 根据当前需求状态重新选择动作。',
      PLANNER_CLARIFICATION_LIMIT: '本次规划已达到澄清轮数上限。请补充完整约束后作为新需求发送。',
      PLANNING_SESSION_CONFLICT: '已有更新的新消息，请重新载入最新会话后继续。',
      OUTPUT_TRUNCATED: '模型输出被截断。请缩短需求，或切换到支持更长输出的模型。',
      CLARIFICATION_ALREADY_RESOLVED: '这组澄清问题已处理，正在恢复最新会话状态。',
      CLARIFICATION_EXPIRED: '这组澄清问题已过期，正在恢复最新问题。',
      CLARIFICATION_NOT_FOUND: '这组澄清问题已失效，正在恢复最新问题。',
      INVALID_CLARIFICATION_ID: '这组澄清问题已失效，正在恢复最新问题。',
      UNKNOWN_TOOL: '计划选择的工具当前不可用，请重新规划或选择其他工具。',
      UNKNOWN_DATASET: '计划选择的知识库当前不可用，请重新规划或选择其他知识库。',
      CANDIDATE_BASE_STALE: '画布已变，候选基于旧版',
    },
    planning: '正在规划…',
    generatingWorkflow: '正在生成工作流…',
    processing: '处理中…',
    resolvingResources: '正在解析资源…',
    understandingRequirements: '正在理解需求…',
    generatingStructure: '正在生成结构…',
    waitingForInformation: '等待补充信息…',
    understoodRequirements: '已理解 {count} 项需求{suffix}',
    understoodCurrentRequest: '已理解当前需求',
    resolvingResource: '正在解析{resource}资源…',
    boundResource: '已绑定{resource}：{name}',
    availableResource: '可用资源',
    requirementLabelsSeparator: '、',
    requirementLabelsPrefix: '：',
    resourceLabels: {
      dataset: '知识库',
      tool: '工具',
      resource: '资源',
    },
    quoteLeft: '「',
    quoteRight: '」',
    activityFailurePrefix: '失败：',
    activitySummarySeparator: ' · ',
    thinking: '思考中…',
    thought: '思考过程',
    other: '其他',
    submitAnswers: '提交回答',
    chooseOne: '单选',
    chooseMultiple: '可多选',
    answerPlaceholder: '请输入你的回答',
    otherPlaceholder: '也可以自己填写',
    toolLabels: {
      build_node: '写入节点',
      validate_graph: '校验',
      search_datasets: '搜索知识库',
      search_tools: '搜索工具',
      list_models: '查看可用模型',
      read_graph: '读取结构',
      read_node: '读取节点',
      connect: '连线',
      disconnect: '断开连线',
      delete_node: '删除节点',
      inspect_node_schema: '查看字段',
      finish: '完成校验',
      ask_user: '询问',
      fail: '失败',
    },
    abortStatuses: {
      superseded_by_new_turn: '已根据你的新消息停止上一轮；已写入的候选图保留。',
      user_abort: '已停止。',
      transport_disconnect: '连接中断；候选图保留。',
    },
    staleApplyNotice: '画布已变，候选基于旧版。可以继续发消息按当前画布改。',
    contractValidationTitle: '合同对账',
    contractValidationSummary: '已满足 {satisfied} · 缺失 {missing} · 冲突 {conflict} · 尚未验证 {unverified}',
    contractValidationLevels: {
      verified: '静态校验通过',
      partially_verified: '静态校验通过，业务效果尚未验证',
      blocked: '存在阻塞项',
      unavailable: '暂无报告',
    },
    contractValidationCategories: {
      node: '节点',
      input: '输入变量',
      output: '输出变量',
      final_output: '最终输出',
      edge: '控制连线',
      resource: '资源',
      edit_scope: '编辑范围',
      contract: '合同',
      graph: '工作流图',
      requirement: '验收检查',
    },
  },
}

export function detectAssistLanguage(instruction) {
  const chineseCount = (String(instruction).match(/[\u3400-\u4dbf\u4e00-\u9fff]/g) || []).length
  const latinCount = (String(instruction).match(/[A-Za-z]/g) || []).length
  return chineseCount * 2 >= latinCount ? 'zh-Hans' : 'en'
}

export function detectRecoveredAssistLanguage(messages, fallback = 'zh-Hans') {
  let language
  for (const message of messages || []) {
    if (message?.role !== 'user')
      continue
    const text = String(message.text || '').trim()
    if (!text)
      continue
    // Match the backend conversation resolver; model names are not locale changes.
    const directive = text.match(/^(?:请\s*)?(?:(?:改用|切换到|使用|用)\s*(中文|英文|英语)|(?:please\s+)?(?:respond|reply|answer|continue)\s+in\s+(Chinese|English)|(?:please\s+)?(?:switch\s+to|use)\s+(Chinese|English))/i)
    if (directive) {
      const target = directive.slice(1).find(Boolean).toLowerCase()
      language = ['中文', 'chinese'].includes(target) ? 'zh-Hans' : 'en'
    }
    else if (!language) {
      language = detectAssistLanguage(text)
    }
  }
  return language || fallback
}

export function assistCopy(language = 'zh-Hans') {
  return COPY[language] || COPY.en
}

export function assistMessage(key, language) {
  return assistCopy(language)[key] || COPY.en[key] || key
}

export function formatAssistCopy(template, values = {}) {
  return Object.entries(values).reduce(
    (text, [key, value]) => text.replaceAll(`{${key}}`, String(value)),
    String(template || ''),
  )
}

const GENERIC_TOOL_SUMMARIES = new Set(['ok', 'error'])

function quoted(copy, value) {
  const text = String(value || '').trim()
  return text ? `${copy.quoteLeft}${text}${copy.quoteRight}` : ''
}

function argumentText(args, ...keys) {
  for (const key of keys) {
    const value = args?.[key]
    if (typeof value === 'string' && value.trim())
      return value.trim()
  }
  return ''
}

function toolActivityBase(name, args, copy) {
  const verb = copy.toolLabels[name] || name || copy.processing
  if (name === 'build_node') {
    const detail = quoted(copy, argumentText(args, 'title', 'type', 'id', 'purpose'))
    return detail ? `${verb}${detail}` : verb
  }
  if (name === 'connect' || name === 'disconnect') {
    const source = argumentText(args, 'source')
    const target = argumentText(args, 'target')
    if (source && target)
      return `${verb} ${source} → ${target}`
    return verb
  }
  if (name === 'delete_node') {
    const nodeId = argumentText(args, 'node_id', 'id')
    return nodeId ? `${verb} ${nodeId}` : verb
  }
  if (name === 'search_datasets' || name === 'search_tools') {
    const query = quoted(copy, argumentText(args, 'query'))
    return query ? `${verb}${query}` : verb
  }
  if (name === 'read_node') {
    const nodeId = argumentText(args, 'id')
    return nodeId ? `${verb} ${nodeId}` : verb
  }
  if (name === 'inspect_node_schema') {
    const nodeType = argumentText(args, 'node_type')
    return nodeType ? `${verb} ${nodeType}` : verb
  }
  return verb
}

function isGenericToolSummary(summary) {
  return GENERIC_TOOL_SUMMARIES.has(String(summary || '').trim().toLowerCase())
}

export function formatAssistToolActivity(event, previousItem, language = 'zh-Hans') {
  const copy = assistCopy(language)
  const name = event?.name || previousItem?.action || ''
  const args = (event?.arguments && typeof event.arguments === 'object' && !Array.isArray(event.arguments))
    ? event.arguments
    : (previousItem?.arguments || {})
  const base = toolActivityBase(name, args, copy)
  if (event?.ok === false) {
    const detail = String(event.error || event.summary || '').trim()
    return detail && !isGenericToolSummary(detail)
      ? `${base}${copy.activityFailurePrefix}${detail}`
      : `${base}${copy.activityFailurePrefix}`.trimEnd()
  }
  const summary = String(event?.summary || '').trim()
  if (!summary || isGenericToolSummary(summary) || base.includes(summary))
    return base
  return `${base}${copy.activitySummarySeparator}${summary}`
}

export function formatAssistCompletionMarkdown(message, language = 'zh-Hans') {
  const copy = assistCopy(language)
  const lines = []
  const summary = String(message?.summary || '').trim()
  if (summary)
    lines.push(summary)
  const diff = message?.diff
  const added = diff?.added?.length || 0
  const updated = (diff?.updated || diff?.changed)?.length || 0
  const removed = diff?.removed?.length || 0
  if (added || updated || removed)
    lines.push(`**${copy.changed}:** +${added} ~${updated} −${removed}`)
  if (message?.validation?.ok)
    lines.push(`**${copy.validationPassed}**`)
  return lines.join('\n\n')
}
