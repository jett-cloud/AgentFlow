/**
 * Aligns with Dify web utils/workflow.ts canRunBySingle.
 */

import { BlockEnum } from './constants.js'

const SINGLE_RUN_TYPES = new Set([
  BlockEnum.LLM,
  BlockEnum.KnowledgeRetrieval,
  BlockEnum.Code,
  BlockEnum.TemplateTransform,
  BlockEnum.QuestionClassifier,
  BlockEnum.HttpRequest,
  BlockEnum.Tool,
  BlockEnum.ParameterExtractor,
  BlockEnum.Iteration,
  BlockEnum.Agent,
  BlockEnum.DocExtractor,
  BlockEnum.Loop,
  BlockEnum.Start,
  BlockEnum.IfElse,
  BlockEnum.VariableAssigner,
  BlockEnum.Assigner,
  BlockEnum.HumanInput,
  BlockEnum.DataSource,
  BlockEnum.TriggerSchedule,
  BlockEnum.TriggerWebhook,
  BlockEnum.TriggerPlugin,
])

/**
 * @param {string} nodeType
 * @param {boolean} [isChildNode]
 */
export function canRunBySingle(nodeType, isChildNode = false) {
  // Child Assigner can break variables in iteration/loop (Dify rule).
  if (isChildNode && nodeType === BlockEnum.Assigner)
    return false
  return SINGLE_RUN_TYPES.has(nodeType)
}
