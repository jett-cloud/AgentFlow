import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { compileTemplate, parse } from '@vue/compiler-sfc'
import { createSSRApp, computed, defineComponent, h } from 'vue'
import * as Vue from 'vue'
import { renderToString } from '@vue/server-renderer'

import { assistCopy } from './assistLanguage.js'

const source = readFileSync(new URL('./AssistLiveAcceptance.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source, { filename: 'AssistLiveAcceptance.vue' })
const compiled = compileTemplate({
  source: descriptor.template.content,
  filename: 'AssistLiveAcceptance.vue',
  id: 'assist-live-acceptance-test',
  compilerOptions: { mode: 'function' },
})
assert.deepEqual(compiled.errors, [])
const render = new Function('Vue', compiled.code)(Vue)

const LiveAcceptance = defineComponent({
  props: {
    request: { type: Object, required: true },
    language: { type: String, default: 'zh-Hans' },
    disabled: { type: Boolean, default: false },
  },
  setup(props) {
    return {
      copy: computed(() => assistCopy(props.language)),
      answer: () => {},
    }
  },
  render,
})

test('live consent asks once for the workflow without exposing its internal node list', async () => {
  const request = {
    request_id: 'a'.repeat(32),
    max_steps: 32,
    max_seconds: 60,
    nodes: [{
      node_id: 'llm',
      title: 'LLM 回答',
      node_type: 'llm',
      capabilities: ['langgenius/deepseek/deepseek/deepseek-flash'],
      may_have_side_effects: false,
    }],
  }
  const html = await renderToString(createSSRApp({
    render: () => h(LiveAcceptance, { request, language: 'zh-Hans' }),
  }))

  assert.match(html, /允许真实运行/)
  assert.match(html, /仅本次 · 最多 32 步 · 60 秒/)
  assert.doesNotMatch(html, /LLM 回答|deepseek|\(llm\)|候选版本|MCP|Agent/)
  assert.equal((html.match(/<button/g) || []).length, 2)
})
