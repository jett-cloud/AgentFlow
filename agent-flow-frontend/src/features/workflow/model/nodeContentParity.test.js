import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const readNode = relativePath => readFileSync(new URL(`../nodes/${relativePath}`, import.meta.url), 'utf8')

test('model nodes keep only the summaries rendered by current Dify', () => {
  const llm = readNode('LLM/LLMNode.vue')
  const classifier = readNode('question-classifier/QuestionClassifierNode.vue')
  const extractor = readNode('parameter-extractor/ParameterExtractorNode.vue')

  assert.doesNotMatch(llm, /promptPreview|prompt-preview/)
  assert.match(classifier, /ModelIcon/)
  assert.match(extractor, /ModelIcon/)
  assert.doesNotMatch(extractor, /No parameters/)
})

test('empty output and transform nodes collapse instead of rendering demo placeholders', () => {
  assert.doesNotMatch(readNode('end/EndNode.vue'), /No outputs configured|empty-outputs/)
  assert.doesNotMatch(readNode('er/AnswerNode.vue'), /No answer content|empty-answer/)
  assert.doesNotMatch(readNode('http-request/HttpRequestNode.vue'), /api\.example\.com/)
  assert.doesNotMatch(readNode('template-transform/TemplateTransformNode.vue'), /Hello \{\{ arg1 \}\}/)
})

test('code and template nodes do not invent canvas summary content', () => {
  assert.doesNotMatch(readNode('code/CodeNode.vue'), /lang-badge-row|Inputs|Outputs/)
  assert.doesNotMatch(readNode('template-transform/TemplateTransformNode.vue'), /TEMPLATE|displayTemplate/)
})

test('tool node renders configured values rather than provider marketing metadata', () => {
  const source = readNode('tool/ToolNode.vue')
  assert.match(source, /configurationRows/)
  assert.doesNotMatch(source, /tool-meta-row|Select tool/)
  assert.match(source, /\*\*\*\*\*\*\*\*/)
})

test('container nodes leave status summaries to the shared header', () => {
  assert.doesNotMatch(readNode('iteration/IterationNode.vue'), /parallel-warning-tag|并行模式/)
  assert.doesNotMatch(readNode('loop/LoopNode.vue'), /loop-count-tag|最大循环/)
})

test('Agent node uses a Dify roster card without task or model previews', () => {
  const source = readNode('t/AgentNode.vue')
  assert.match(source, /agent-roster-card/)
  assert.doesNotMatch(source, /taskPreview|model-bar/)
})
