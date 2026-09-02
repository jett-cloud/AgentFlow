/**
 * Initial draft graphs aligned with Dify use-workflow-template.ts
 * Chatflow: Start → LLM → Answer
 * Workflow: empty graph (canvas injects start-placeholder client-side)
 */

import { BlockEnum } from './constants.js'
import {
  flowToGraph,
  generateNewNode,
  START_INITIAL_POSITION,
} from './dsl.js'
import { AppMode, isChatflowMode } from './appModes.js'

/** Dify NODE_WIDTH(240) + X_OFFSET(60) */
export const NODE_WIDTH_X_OFFSET = 300

function defaultFeatures() {
  return { retriever_resource: { enabled: true } }
}

export function buildWorkflowInitialDraftPayload() {
  return {
    graph: { nodes: [], edges: [] },
    features: defaultFeatures(),
    environment_variables: [],
    conversation_variables: [],
  }
}

/**
 * Mirrors web/.../use-workflow-template.ts chat branch.
 */
export function buildChatflowInitialGraph() {
  const { newNode: startNode } = generateNewNode({
    type: BlockEnum.Start,
    position: { ...START_INITIAL_POSITION },
  })

  const { newNode: llmNode } = generateNewNode({
    type: BlockEnum.LLM,
    id: 'llm',
    position: {
      x: START_INITIAL_POSITION.x + NODE_WIDTH_X_OFFSET,
      y: START_INITIAL_POSITION.y,
    },
    data: {
      memory: {
        window: { enabled: false, size: 10 },
        query_prompt_template: '{{#sys.query#}}\n\n{{#sys.files#}}',
      },
      selected: true,
    },
  })

  const { newNode: answerNode } = generateNewNode({
    type: BlockEnum.Answer,
    id: 'answer',
    position: {
      x: START_INITIAL_POSITION.x + NODE_WIDTH_X_OFFSET * 2,
      y: START_INITIAL_POSITION.y,
    },
    data: {
      answer: `{{#${llmNode.id}.text#}}`,
    },
  })

  const edges = [
    {
      id: `${startNode.id}-${llmNode.id}`,
      source: startNode.id,
      sourceHandle: 'source',
      target: llmNode.id,
      targetHandle: 'target',
    },
    {
      id: `${llmNode.id}-${answerNode.id}`,
      source: llmNode.id,
      sourceHandle: 'source',
      target: answerNode.id,
      targetHandle: 'target',
    },
  ]

  return flowToGraph([startNode, llmNode, answerNode], edges)
}

export function buildChatflowInitialDraftPayload() {
  return {
    graph: buildChatflowInitialGraph(),
    features: defaultFeatures(),
    environment_variables: [],
    conversation_variables: [],
  }
}

export function buildInitialDraftPayloadForMode(mode) {
  if (isChatflowMode(mode) || mode === AppMode.ADVANCED_CHAT)
    return buildChatflowInitialDraftPayload()
  return buildWorkflowInitialDraftPayload()
}
