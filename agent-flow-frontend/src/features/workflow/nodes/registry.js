// src/views/copilot/components/workflow/registry.js
import { markRaw } from 'vue'

// 自定义边
import CustomEdge from '../canvas/components/CustomEdge.vue'

// 节点 Node 组件全量导入
import BaseNode from './base/BaseNode.vue'
import LLMNode from './LLM/LLMNode.vue'
import StartNode from './t/StartNode.vue'
import EndNode from './end/EndNode.vue'
import AnswerNode from './er/AnswerNode.vue'
import IfElseNode from './if-else/IfElseNode.vue'
import CodeNode from './code/CodeNode.vue'
import KnowledgeRetrievalNode from './knowledge-retrieval/KnowledgeRetrievalNode.vue'
import QuestionClassifierNode from './question-classifier/QuestionClassifierNode.vue'
import ParameterExtractorNode from './parameter-extractor/ParameterExtractorNode.vue'
import TemplateTransformNode from './template-transform/TemplateTransformNode.vue'
import HttpRequestNode from './http-request/HttpRequestNode.vue'
import ToolNode from './tool/ToolNode.vue'
import VariableAssignerNode from './variable-assigner/VariableAssignerNode.vue'
import VariableAggregatorNode from './variable-aggregator/VariableAggregatorNode.vue'
import IterationNode from './iteration/IterationNode.vue'
import IterationStartNode from './iteration-start/IterationStartNode.vue'
import LoopNode from './loop/LoopNode.vue'
import LoopStartNode from './loop-start/LoopStartNode.vue'
import LoopEndNode from './loop-end/LoopEndNode.vue'
import DocExtractorNode from './document-extractor/DocExtractorNode.vue'
import ListOperatorNode from './list-operator/ListOperatorNode.vue'
import HumanInputNode from './human-input/HumanInputNode.vue'
import AgentNode from './t/AgentNode.vue'
import DataSourceNode from './data-source/DataSourceNode.vue'
import KnowledgeBaseNode from './knowledge-base/KnowledgeBaseNode.vue'
import ScheduleTriggerNode from './trigger-schedule/ScheduleTriggerNode.vue'
import WebhookTriggerNode from './trigger-webhook/WebhookTriggerNode.vue'
import PluginTriggerNode from './trigger-plugin/PluginTriggerNode.vue'
import StartPlaceholderNode from './start-placeholder/StartPlaceholderNode.vue'
import NoteNode from './note/NoteNode.vue'

// 右侧抽屉 Panel 组件全量导入
import LLMPanel from './LLM/LLMPanel.vue'
import StartPanel from './t/StartPanel.vue'
import EndPanel from './end/EndPanel.vue'
import AnswerPanel from './er/AnswerPanel.vue'
import IfElsePanel from './if-else/IfElsePanel.vue'
import CodePanel from './code/CodePanel.vue'
import KnowledgeRetrievalPanel from './knowledge-retrieval/KnowledgeRetrievalPanel.vue'
import QuestionClassifierPanel from './question-classifier/QuestionClassifierPanel.vue'
import ParameterExtractorPanel from './parameter-extractor/ParameterExtractorPanel.vue'
import TemplateTransformPanel from './template-transform/TemplateTransformPanel.vue'
import HttpRequestPanel from './http-request/HttpRequestPanel.vue'
import ToolPanel from './tool/ToolPanel.vue'
import VariableAssignerPanel from './variable-assigner/VariableAssignerPanel.vue'
import VariableAggregatorPanel from './variable-aggregator/VariableAggregatorPanel.vue'
import IterationPanel from './iteration/IterationPanel.vue'
import LoopPanel from './loop/LoopPanel.vue'
import DocExtractorPanel from './document-extractor/DocExtractorPanel.vue'
import ListOperatorPanel from './list-operator/ListOperatorPanel.vue'
import HumanInputPanel from './human-input/HumanInputPanel.vue'
import AgentPanel from './t/AgentPanel.vue'
import DataSourcePanel from './data-source/DataSourcePanel.vue'
import KnowledgeBasePanel from './knowledge-base/KnowledgeBasePanel.vue'
import StartPlaceholderPanel from './start-placeholder/StartPlaceholderPanel.vue'
import ScheduleTriggerPanel from './trigger-schedule/ScheduleTriggerPanel.vue'
import WebhookTriggerPanel from './trigger-webhook/WebhookTriggerPanel.vue'
import PluginTriggerPanel from './trigger-plugin/PluginTriggerPanel.vue'

/**
 * 1. 对应 Dify 官方所�?25+ 节点类型�?NodeComponentMap (映射�?
 * 传递给 VueFlow �?:node-types 属性进行动态模板注�? */
export const NODE_COMPONENT_MAP = {
  // 基础核心节点
  start: markRaw(StartNode),
  'start-placeholder': markRaw(StartPlaceholderNode),
  end: markRaw(EndNode),
  answer: markRaw(AnswerNode),
  llm: markRaw(LLMNode),

  // 逻辑控制与数据变换节点
  'knowledge-retrieval': markRaw(KnowledgeRetrievalNode),
  'question-classifier': markRaw(QuestionClassifierNode),
  'if-else': markRaw(IfElseNode),
  code: markRaw(CodeNode),
  'template-transform': markRaw(TemplateTransformNode),
  'http-request': markRaw(HttpRequestNode),
  tool: markRaw(ToolNode),
  assigner: markRaw(VariableAssignerNode),
  'variable-assigner': markRaw(VariableAggregatorNode),
  'variable-aggregator': markRaw(VariableAggregatorNode),
  'parameter-extractor': markRaw(ParameterExtractorNode),
  iteration: markRaw(IterationNode),
  'iteration-start': markRaw(IterationStartNode),
  'custom-iteration-start': markRaw(IterationStartNode),
  loop: markRaw(LoopNode),
  'loop-start': markRaw(LoopStartNode),
  'custom-loop-start': markRaw(LoopStartNode),
  'loop-end': markRaw(LoopEndNode),
  'custom-simple': markRaw(LoopEndNode),
  'document-extractor': markRaw(DocExtractorNode),
  'list-operator': markRaw(ListOperatorNode),

  // Agent 与触发器扩展节点
  agent: markRaw(AgentNode),
  'agent-v2': markRaw(AgentNode),
  datasource: markRaw(DataSourceNode),
  'knowledge-index': markRaw(KnowledgeBaseNode),
  'human-input': markRaw(HumanInputNode),
  'trigger-schedule': markRaw(ScheduleTriggerNode),
  'trigger-webhook': markRaw(WebhookTriggerNode),
  'trigger-plugin': markRaw(PluginTriggerNode),
  note: markRaw(NoteNode),

  // 通用默认兜底节点
  default: markRaw(BaseNode),
  // 后端 DSL type 为 custom 时兜底
  custom: markRaw(BaseNode),
}

/** vue-flow 边类型注册表 */
export const EDGE_COMPONENT_MAP = {
  custom: markRaw(CustomEdge),
  default: markRaw(CustomEdge),
  smoothstep: markRaw(CustomEdge),
}

/**
 * 2. 对应 Dify 官方所有节点类型的 PanelComponentMap (右侧面板映射�?
 * 根据选中�?node.type 动态查找对应的右侧配置面板组件
 */
export const PANEL_COMPONENT_MAP = {
  start: markRaw(StartPanel),
  'start-placeholder': markRaw(StartPlaceholderPanel),
  llm: markRaw(LLMPanel),
  end: markRaw(EndPanel),
  answer: markRaw(AnswerPanel),
  'if-else': markRaw(IfElsePanel),
  code: markRaw(CodePanel),
  'knowledge-retrieval': markRaw(KnowledgeRetrievalPanel),
  'question-classifier': markRaw(QuestionClassifierPanel),
  'parameter-extractor': markRaw(ParameterExtractorPanel),
  'template-transform': markRaw(TemplateTransformPanel),
  'http-request': markRaw(HttpRequestPanel),
  tool: markRaw(ToolPanel),
  assigner: markRaw(VariableAssignerPanel),
  'variable-assigner': markRaw(VariableAggregatorPanel),
  'variable-aggregator': markRaw(VariableAggregatorPanel),
  iteration: markRaw(IterationPanel),
  loop: markRaw(LoopPanel),
  'document-extractor': markRaw(DocExtractorPanel),
  'list-operator': markRaw(ListOperatorPanel),
  'human-input': markRaw(HumanInputPanel),
  agent: markRaw(AgentPanel),
  'agent-v2': markRaw(AgentPanel),
  datasource: markRaw(DataSourcePanel),
  'knowledge-index': markRaw(KnowledgeBasePanel),
  'trigger-schedule': markRaw(ScheduleTriggerPanel),
  'trigger-webhook': markRaw(WebhookTriggerPanel),
  'trigger-plugin': markRaw(PluginTriggerPanel),
}
