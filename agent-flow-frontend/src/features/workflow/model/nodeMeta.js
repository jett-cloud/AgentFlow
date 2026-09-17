// src/views/copilot/components/workflow/core/nodeMeta.js
//
// 每种节点类型的：显示名 / 默认 data / 连线能力 / 是否容器。
// 对齐 Dify web/app/components/workflow/nodes/*/default.ts 的 defaultValue 思路，
// 但只保留跑通画布所必需的最小默认字段（面板会再补齐细节字段）。

import {
  BlockEnum,
  START_NODE_TYPES,
  TERMINAL_NODE_TYPES,
  NON_CONNECTABLE_NODE_TYPES,
  CONTAINER_NODE_TYPES,
  CONTAINER_START_NODE_TYPES,
  CONTAINER_DEFAULT_WIDTH,
  CONTAINER_DEFAULT_HEIGHT,
} from './constants.js'
import { LIST_OPERATOR_DEFAULTS } from '../nodes/list-operator/listOperator.js'
import { CODE_NODE_DEFAULTS } from '../nodes/code/codeNode.js'
import { TEMPLATE_TRANSFORM_DEFAULTS } from '../nodes/template-transform/templateTransform.js'
import { DOCUMENT_EXTRACTOR_DEFAULTS } from '../nodes/document-extractor/documentExtractor.js'
import { HTTP_REQUEST_DEFAULTS } from '../nodes/http-request/httpRequest.js'
import { TOOL_DEFAULTS } from '../nodes/tool/toolNode.js'
import { ITERATION_DEFAULTS } from '../nodes/iteration/iterationNode.js'
import { LOOP_DEFAULTS } from '../nodes/loop/loopNode.js'
import { IF_ELSE_DEFAULTS } from '../nodes/if-else/ifElseNode.js'
import { QUESTION_CLASSIFIER_DEFAULTS } from '../nodes/question-classifier/questionClassifierNode.js'
import { HUMAN_INPUT_DEFAULTS } from '../nodes/human-input/humanInputNode.js'
import { LLM_DEFAULTS } from '../nodes/llm/llmNode.js'
import { PARAMETER_EXTRACTOR_DEFAULTS } from '../nodes/parameter-extractor/parameterExtractorNode.js'
import { KNOWLEDGE_RETRIEVAL_DEFAULTS } from '../nodes/knowledge-retrieval/knowledgeRetrievalNode.js'
import { KNOWLEDGE_BASE_DEFAULTS } from '../nodes/knowledge-base/knowledgeBaseNode.js'
import { DATA_SOURCE_DEFAULTS } from '../nodes/data-source/dataSourceNode.js'
import { END_DEFAULTS } from '../nodes/end/endNode.js'
import { ANSWER_DEFAULTS } from '../nodes/er/answerNode.js'
import { LOOP_END_DEFAULTS } from '../nodes/loop-end/loopEndNode.js'
import { NOTE_DEFAULTS } from '../nodes/note/noteNode.js'
import { START_PLACEHOLDER_DEFAULTS } from '../nodes/start-placeholder/startPlaceholderNode.js'
import { ITERATION_START_DEFAULTS } from '../nodes/iteration-start/iterationStartNode.js'
import { LOOP_START_DEFAULTS } from '../nodes/loop-start/loopStartNode.js'

/**
 * 节点元信息表。
 * key = BlockEnum 值；value = { title, defaultData }
 * defaultData 不包含 title/type（由工厂统一注入）。
 */
export const NODE_META = {
  [BlockEnum.Start]: {
    title: '开始',
    defaultData: { variables: [] },
  },
  [BlockEnum.End]: {
    title: '结束',
    defaultData: END_DEFAULTS,
  },
  [BlockEnum.Answer]: {
    title: '直接回复',
    defaultData: ANSWER_DEFAULTS,
  },
  [BlockEnum.LLM]: {
    title: 'LLM',
    defaultData: LLM_DEFAULTS,
  },
  [BlockEnum.KnowledgeRetrieval]: {
    title: '知识检索',
    defaultData: KNOWLEDGE_RETRIEVAL_DEFAULTS,
  },
  [BlockEnum.QuestionClassifier]: {
    title: '问题分类器',
    defaultData: QUESTION_CLASSIFIER_DEFAULTS,
  },
  [BlockEnum.IfElse]: {
    title: '条件分支',
    defaultData: IF_ELSE_DEFAULTS,
  },
  [BlockEnum.Code]: {
    title: '代码执行',
    defaultData: CODE_NODE_DEFAULTS,
  },
  [BlockEnum.TemplateTransform]: {
    title: '模板转换',
    defaultData: TEMPLATE_TRANSFORM_DEFAULTS,
  },
  [BlockEnum.HttpRequest]: {
    title: 'HTTP 请求',
    defaultData: HTTP_REQUEST_DEFAULTS,
  },
  [BlockEnum.Assigner]: {
    title: '变量赋值',
    defaultData: { version: '2', items: [] },
  },
  [BlockEnum.VariableAssigner]: {
    title: '变量聚合器',
    defaultData: {
      output_type: 'any',
      variables: [],
      advanced_settings: { group_enabled: false, groups: [] },
    },
  },
  [BlockEnum.Tool]: {
    title: '工具',
    defaultData: TOOL_DEFAULTS,
  },
  [BlockEnum.ParameterExtractor]: {
    title: '参数提取',
    defaultData: PARAMETER_EXTRACTOR_DEFAULTS,
  },
  [BlockEnum.DocExtractor]: {
    title: '文档提取器',
    defaultData: DOCUMENT_EXTRACTOR_DEFAULTS,
  },
  [BlockEnum.ListFilter]: {
    title: '列表操作',
    defaultData: LIST_OPERATOR_DEFAULTS,
  },
  [BlockEnum.Agent]: {
    title: 'Agent',
    defaultData: {
      version: '2',
      agent_node_kind: 'dify_agent',
      agent_binding: { binding_type: 'inline_agent' },
      agent_task: '',
      agent_declared_outputs: [],
    },
  },
  'agent-v2': {
    // Menu/load alias only; persist as type "agent" + version "2".
    title: 'Agent',
    defaultData: {
      type: 'agent',
      version: '2',
      agent_node_kind: 'dify_agent',
      agent_binding: { binding_type: 'inline_agent' },
      agent_task: '',
      agent_declared_outputs: [],
    },
  },
  [BlockEnum.HumanInput]: {
    title: '人工介入',
    defaultData: HUMAN_INPUT_DEFAULTS,
  },
  [BlockEnum.Iteration]: {
    title: '迭代',
    defaultData: ITERATION_DEFAULTS,
    width: CONTAINER_DEFAULT_WIDTH,
    height: CONTAINER_DEFAULT_HEIGHT,
  },
  [BlockEnum.Loop]: {
    title: '循环',
    defaultData: LOOP_DEFAULTS,
    width: CONTAINER_DEFAULT_WIDTH,
    height: CONTAINER_DEFAULT_HEIGHT,
  },
  [BlockEnum.IterationStart]: {
    title: '',
    defaultData: ITERATION_START_DEFAULTS,
  },
  [BlockEnum.LoopStart]: {
    title: '',
    defaultData: LOOP_START_DEFAULTS,
  },
  [BlockEnum.LoopEnd]: {
    title: '退出循环',
    defaultData: LOOP_END_DEFAULTS,
  },
  [BlockEnum.TriggerSchedule]: {
    title: '定时触发',
    defaultData: { cron: '0 0 * * *' },
  },
  [BlockEnum.TriggerWebhook]: {
    title: 'Webhook 触发',
    defaultData: {},
  },
  [BlockEnum.TriggerPlugin]: {
    title: '插件触发',
    defaultData: {},
  },
  [BlockEnum.DataSource]: {
    title: '数据源',
    defaultData: DATA_SOURCE_DEFAULTS,
  },
  [BlockEnum.KnowledgeBase]: {
    title: '知识库',
    defaultData: KNOWLEDGE_BASE_DEFAULTS,
  },
  [BlockEnum.StartPlaceholder]: {
    title: START_PLACEHOLDER_DEFAULTS.title,
    defaultData: START_PLACEHOLDER_DEFAULTS,
  },
  [BlockEnum.Note]: {
    title: '便签',
    defaultData: NOTE_DEFAULTS,
  },
}

/** 该类型是否有“输入”锚点（能作为连线终点） */
export function canConnectAsTarget(nodeType) {
  return !CONTAINER_START_NODE_TYPES.includes(nodeType)
    && !START_NODE_TYPES.includes(nodeType)
    && !NON_CONNECTABLE_NODE_TYPES.includes(nodeType)
}

/** 该类型是否有“输出”锚点（能作为连线起点） */
export function canConnectAsSource(nodeType) {
  return !TERMINAL_NODE_TYPES.includes(nodeType) && !NON_CONNECTABLE_NODE_TYPES.includes(nodeType)
}

export function getSelectableBlocksForDirection(types, direction = 'free') {
  if (direction === 'before')
    return types.filter(canConnectAsSource)
  if (direction === 'after')
    return types.filter(canConnectAsTarget)
  if (direction === 'insert')
    return types.filter(type => canConnectAsSource(type) && canConnectAsTarget(type))
  return types
}

/** 是否容器型节点 */
export function isContainerNode(nodeType) {
  return CONTAINER_NODE_TYPES.includes(nodeType)
}

/** 是否容器内部虚拟起始节点 */
export function isContainerStartNode(nodeType) {
  return CONTAINER_START_NODE_TYPES.includes(nodeType)
}

/** 取默认标题（找不到就用类型名兜底） */
export function getNodeTitle(nodeType) {
  return NODE_META[nodeType]?.title ?? nodeType
}

/** 深拷贝该类型的默认 data（含 type 字段） */
export function getDefaultNodeData(nodeType) {
  const meta = NODE_META[nodeType]
  const base = meta ? structuredClone(meta.defaultData) : {}
  return { type: nodeType, title: getNodeTitle(nodeType), ...base }
}

/** 可从“添加节点”菜单里选择的业务节点（排除内部/虚拟/占位/开始类型） */
export const SELECTABLE_BLOCKS = [
  BlockEnum.LLM,
  BlockEnum.KnowledgeRetrieval,
  BlockEnum.QuestionClassifier,
  BlockEnum.IfElse,
  BlockEnum.Code,
  BlockEnum.TemplateTransform,
  BlockEnum.HttpRequest,
  BlockEnum.Tool,
  BlockEnum.ParameterExtractor,
  BlockEnum.Assigner,
  BlockEnum.VariableAssigner,
  BlockEnum.DocExtractor,
  BlockEnum.ListFilter,
  BlockEnum.Agent,
  BlockEnum.KnowledgeBase,
  BlockEnum.HumanInput,
  BlockEnum.Iteration,
  BlockEnum.Loop,
  BlockEnum.Answer,
  BlockEnum.End,
]

/** 工具 Tab */
export const TOOL_BLOCKS = [BlockEnum.Tool, BlockEnum.HttpRequest]

/** 触发器（仅开始节点流程使用，不进普通加节点菜单） */
export const TRIGGER_BLOCKS = [
  BlockEnum.TriggerSchedule,
  BlockEnum.TriggerWebhook,
  BlockEnum.TriggerPlugin,
  BlockEnum.DataSource,
]

/**
 * Start 页签 / start-placeholder 面板共用的入口选项
 *（对齐 web block-selector START_BLOCKS，不含 datasource 与动态插件目录）
 */
export const START_BLOCK_OPTIONS = [
  {
    type: BlockEnum.Start,
    title: '用户输入',
    desc: '通过 WebApp / API 手动触发，最常用',
    badge: '常用',
  },
  {
    type: BlockEnum.TriggerSchedule,
    title: '定时触发',
    desc: '按 Cron 表达式周期性启动工作流',
  },
  {
    type: BlockEnum.TriggerWebhook,
    title: 'Webhook 触发',
    desc: '接收外部 HTTP 回调后启动',
  },
  {
    type: BlockEnum.TriggerPlugin,
    title: '插件触发',
    desc: '由已安装的触发器插件事件启动',
  },
]

/** 迭代/循环容器内可添加的节点 */
const CONTAINER_EXCLUDED_BLOCKS = new Set([
  BlockEnum.End,
  BlockEnum.Iteration,
  BlockEnum.Loop,
  BlockEnum.DataSource,
  BlockEnum.KnowledgeBase,
])

export const CONTAINER_SELECTABLE_BLOCKS = [
  ...SELECTABLE_BLOCKS.filter(type => !CONTAINER_EXCLUDED_BLOCKS.has(type)),
  BlockEnum.LoopEnd,
]

export function getBlockGroup(type) {
  if (TRIGGER_BLOCKS.includes(type) || type === BlockEnum.DataSource) return '入口'
  if ([BlockEnum.LLM, BlockEnum.Agent, BlockEnum.QuestionClassifier, BlockEnum.ParameterExtractor].includes(type)) return 'AI'
  if ([BlockEnum.KnowledgeRetrieval, BlockEnum.KnowledgeBase, BlockEnum.DocExtractor].includes(type)) return '知识库'
  if ([BlockEnum.IfElse, BlockEnum.Iteration, BlockEnum.Loop, BlockEnum.LoopEnd, BlockEnum.HumanInput].includes(type)) return '逻辑'
  if ([BlockEnum.Code, BlockEnum.TemplateTransform, BlockEnum.Assigner, BlockEnum.VariableAssigner, BlockEnum.ListFilter].includes(type)) return '转换'
  if (TOOL_BLOCKS.includes(type)) return '工具'
  return '输出'
}
