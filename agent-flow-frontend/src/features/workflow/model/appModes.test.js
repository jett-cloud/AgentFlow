import assert from 'node:assert/strict'
import test from 'node:test'

import {
  AppMode,
  appModeLabel,
  debugActionLabel,
  isChatflowMode,
  isWorkflowStudioMode,
} from './appModes.js'
import {
  buildChatflowInitialDraftPayload,
  buildInitialDraftPayloadForMode,
  buildWorkflowInitialDraftPayload,
  NODE_WIDTH_X_OFFSET,
} from './workflowTemplates.js'
import { START_INITIAL_POSITION } from './dsl.js'

test('appMode helpers distinguish workflow vs chatflow', () => {
  assert.equal(isChatflowMode(AppMode.ADVANCED_CHAT), true)
  assert.equal(isChatflowMode(AppMode.WORKFLOW), false)
  assert.equal(appModeLabel(AppMode.ADVANCED_CHAT), 'Chatflow')
  assert.equal(appModeLabel(AppMode.WORKFLOW), '工作流')
  assert.equal(appModeLabel(AppMode.CHAT), '聊天助手')
  assert.equal(isWorkflowStudioMode(AppMode.WORKFLOW), true)
  assert.equal(isWorkflowStudioMode(AppMode.CHAT), false)
  assert.equal(debugActionLabel(AppMode.WORKFLOW), '测试运行')
  assert.equal(debugActionLabel(AppMode.ADVANCED_CHAT), '调试与预览')
  assert.equal(debugActionLabel(AppMode.ADVANCED_CHAT, { isRunning: true }), '运行中…')
})

test('workflow initial draft is empty graph (start-placeholder injected client-side)', () => {
  const payload = buildWorkflowInitialDraftPayload()
  assert.deepEqual(payload.graph, { nodes: [], edges: [] })
  assert.ok(payload.features?.retriever_resource)
})

test('chatflow initial draft mirrors Dify Start → LLM → Answer', () => {
  const payload = buildChatflowInitialDraftPayload()
  const { nodes, edges } = payload.graph
  assert.equal(nodes.length, 3)
  assert.equal(edges.length, 2)

  const types = nodes.map(n => n.data?.type)
  assert.deepEqual(types, ['start', 'llm', 'answer'])

  const llm = nodes.find(n => n.id === 'llm')
  const answer = nodes.find(n => n.id === 'answer')
  assert.ok(llm)
  assert.ok(answer)
  assert.equal(llm.position.x, START_INITIAL_POSITION.x + NODE_WIDTH_X_OFFSET)
  assert.equal(answer.position.x, START_INITIAL_POSITION.x + NODE_WIDTH_X_OFFSET * 2)
  assert.equal(llm.data.memory?.query_prompt_template, '{{#sys.query#}}\n\n{{#sys.files#}}')
  assert.equal(answer.data.answer, '{{#llm.text#}}')

  assert.equal(edges[0].source, nodes.find(n => n.data.type === 'start').id)
  assert.equal(edges[0].target, 'llm')
  assert.equal(edges[1].source, 'llm')
  assert.equal(edges[1].target, 'answer')
})

test('buildInitialDraftPayloadForMode branches by mode', () => {
  assert.equal(buildInitialDraftPayloadForMode(AppMode.WORKFLOW).graph.nodes.length, 0)
  assert.equal(buildInitialDraftPayloadForMode(AppMode.ADVANCED_CHAT).graph.nodes.length, 3)
})
