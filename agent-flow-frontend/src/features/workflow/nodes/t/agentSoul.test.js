import test from 'node:test'
import assert from 'node:assert/strict'
import {
  applySoulPromptAndModel,
  normalizeAgentSoul,
  withSoulDifyTools,
  withSoulKnowledgeSets,
} from './agentSoul.js'

test('normalizeAgentSoul fills tools and knowledge defaults', () => {
  const soul = normalizeAgentSoul({ prompt: { system_prompt: 'hi' } })
  assert.equal(soul.schema_version, 1)
  assert.equal(soul.prompt.system_prompt, 'hi')
  assert.deepEqual(soul.tools.dify_tools, [])
  assert.deepEqual(soul.tools.cli_tools, [])
  assert.deepEqual(soul.knowledge.sets, [])
})

test('normalizeAgentSoul preserves extra known sections', () => {
  const soul = normalizeAgentSoul({
    sandbox: { enabled: true },
    human: { contacts: [] },
    tools: {
      dify_tools: [{
        provider_id: 'p1',
        tool_name: 't1',
        credential_type: 'unauthorized',
      }],
    },
  })
  assert.equal(soul.sandbox.enabled, true)
  assert.ok(Array.isArray(soul.human.contacts))
  assert.equal(soul.tools.dify_tools[0].credential_type, 'unauthorized')
})

test('withSoulDifyTools / withSoulKnowledgeSets round-trip', () => {
  let soul = normalizeAgentSoul({})
  soul = withSoulDifyTools(soul, [{
    provider_id: 'p1',
    provider_type: 'mcp',
    tool_name: 'list',
    credential_type: 'unauthorized',
  }])
  soul = withSoulKnowledgeSets(soul, [{
    id: 'ks1',
    name: 'Set A',
    datasets: [{ id: 'd1', name: 'D' }],
    query: { mode: 'user_query', value: 'q' },
    retrieval: { mode: 'multiple', top_k: 3, reranking_enable: true },
  }])
  assert.equal(soul.tools.dify_tools[0].tool_name, 'list')
  assert.equal(soul.knowledge.sets[0].query.mode, 'user_query')
  assert.equal(soul.knowledge.sets[0].retrieval.top_k, 3)

  const applied = applySoulPromptAndModel({
    soul,
    prompt: 'system',
    soulModel: { model_provider: 'openai', model: 'gpt-4o', plugin_id: 'langgenius/openai' },
  })
  assert.equal(applied.prompt.system_prompt, 'system')
  assert.equal(applied.model.model, 'gpt-4o')
  assert.equal(applied.tools.dify_tools.length, 1)
  assert.equal(applied.knowledge.sets.length, 1)
})
