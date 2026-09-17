// src/views/copilot/components/workflow/core/constants.js
//
// 画布内核常量。严格对齐 Dify React 源码：
//   - web/app/components/workflow/types.ts (BlockEnum)
//   - web/app/components/workflow/constants.ts (CUSTOM_NODE / CUSTOM_EDGE / z-index)
//   - web/app/components/workflow/nodes/iteration-start|loop-start/constants.ts
//
// 关键约定：后端 graph_dict 里每个 node 的 vue-flow "type" 都是 'custom'，
// 真正的业务类型放在 data.type（BlockEnum 字符串值）。导入/导出在 dsl.js 中转换。

/** 节点业务类型（= Dify BlockEnum 的字符串值，务必保持一致以对齐后端 DSL） */
export const BlockEnum = {
  Start: 'start',
  StartPlaceholder: 'start-placeholder',
  End: 'end',
  Answer: 'answer',
  LLM: 'llm',
  KnowledgeRetrieval: 'knowledge-retrieval',
  QuestionClassifier: 'question-classifier',
  IfElse: 'if-else',
  Code: 'code',
  TemplateTransform: 'template-transform',
  HttpRequest: 'http-request',
  Assigner: 'assigner',
  VariableAssigner: 'variable-assigner',
  Tool: 'tool',
  ParameterExtractor: 'parameter-extractor',
  Iteration: 'iteration',
  IterationStart: 'iteration-start',
  DocExtractor: 'document-extractor',
  ListFilter: 'list-operator',
  Agent: 'agent',
  Loop: 'loop',
  LoopStart: 'loop-start',
  LoopEnd: 'loop-end',
  HumanInput: 'human-input',
  DataSource: 'datasource',
  KnowledgeBase: 'knowledge-index',
  TriggerSchedule: 'trigger-schedule',
  TriggerWebhook: 'trigger-webhook',
  TriggerPlugin: 'trigger-plugin',
  Note: 'note',
}

/** AgentFlow 旧草稿使用过的非 Dify 节点类型，仅用于导入迁移。 */
export const LEGACY_VARIABLE_AGGREGATOR_TYPE = 'variable-aggregator'

/** vue-flow 层的自定义节点/边类型（对齐 Dify constants.ts） */
export const CUSTOM_NODE = 'custom'
export const CUSTOM_SIMPLE_NODE = 'custom-simple'
export const CUSTOM_EDGE = 'custom'
export const CUSTOM_ITERATION_START_NODE = 'custom-iteration-start'
export const CUSTOM_LOOP_START_NODE = 'custom-loop-start'
export const CUSTOM_NOTE_NODE = 'custom-note'

/** z-index（对齐 Dify constants.ts） */
export const NODE_Z_INDEX = 10
export const ITERATION_NODE_Z_INDEX = 1
export const NESTED_ELEMENT_Z_INDEX = 1001
export const ITERATION_CHILDREN_Z_INDEX = 1002

/** 默认锚点 id（对齐 BaseNode.vue 里 Handle 的 id） */
export const DEFAULT_SOURCE_HANDLE = 'source'
export const DEFAULT_TARGET_HANDLE = 'target'

/**
 * 起点类节点：只能作为连线的起点（没有输入锚点），且是流程的根。
 * 对齐 Dify getValidTreeNodes 的 startNodes 判定。
 */
export const START_NODE_TYPES = [
  BlockEnum.Start,
  BlockEnum.TriggerSchedule,
  BlockEnum.TriggerWebhook,
  BlockEnum.TriggerPlugin,
  BlockEnum.DataSource,
]

/** 终点类节点：只能作为连线的终点（没有输出锚点） */
export const TERMINAL_NODE_TYPES = [BlockEnum.End, BlockEnum.LoopEnd]

/** 画布注释与客户端占位节点：不参与工作流连线。 */
export const NON_CONNECTABLE_NODE_TYPES = [BlockEnum.Note, BlockEnum.StartPlaceholder]

/** 容器型节点（内部承载子图） */
export const CONTAINER_NODE_TYPES = [BlockEnum.Iteration, BlockEnum.Loop]

/** 容器内部的虚拟起始节点类型 */
export const CONTAINER_START_NODE_TYPES = [BlockEnum.IterationStart, BlockEnum.LoopStart]

/** 支持“错误处理分支”的节点（对齐 utils/workflow.ts hasErrorHandleNode） */
export const ERROR_HANDLE_NODE_TYPES = [
  BlockEnum.LLM,
  BlockEnum.Tool,
  BlockEnum.HttpRequest,
  BlockEnum.Code,
  BlockEnum.Agent,
]

/** 支持“失败重试”的节点（对齐 utils/node.ts hasRetryNode） */
export const RETRY_NODE_TYPES = [
  BlockEnum.LLM,
  BlockEnum.Tool,
  BlockEnum.HttpRequest,
  BlockEnum.Code,
]

/** 画布交互相关的默认尺寸 */
export const CONTAINER_DEFAULT_WIDTH = 640
export const CONTAINER_DEFAULT_HEIGHT = 340
