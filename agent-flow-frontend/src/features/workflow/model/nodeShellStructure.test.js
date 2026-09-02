import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const baseNode = readFileSync(new URL('../nodes/base/BaseNode.vue', import.meta.url), 'utf8')
const nodeHandle = readFileSync(new URL('../nodes/base/NodeHandle.vue', import.meta.url), 'utf8')
const nodeControl = readFileSync(new URL('../nodes/base/NodeControl.vue', import.meta.url), 'utf8')
const containerResizerUrl = new URL('../nodes/base/ContainerResizer.vue', import.meta.url)
const registry = readFileSync(new URL('../nodes/registry.js', import.meta.url), 'utf8')
const blockSelectorMenu = readFileSync(new URL('../canvas/components/BlockSelectorMenu.vue', import.meta.url), 'utf8')
const variableAggregatorPanel = readFileSync(new URL('../nodes/variable-aggregator/VariableAggregatorPanel.vue', import.meta.url), 'utf8')
const variableAggregatorConfig = readFileSync(new URL('../nodes/variable-aggregator/useVariableAggregatorConfig.js', import.meta.url), 'utf8')
const workflowCanvas = readFileSync(new URL('../canvas/WorkflowCanvas.vue', import.meta.url), 'utf8')

test('BaseNode delegates structural rules to nodePresentation', () => {
  assert.match(baseNode, /getNodePresentation/)
  assert.match(baseNode, /getEntryLabel/)
  assert.doesNotMatch(baseNode, /const noTargetTypes/)
  assert.doesNotMatch(baseNode, /const noSourceTypes/)
})

test('node controls are available on hover or focus without requiring selection', () => {
  assert.match(baseNode, /v-if="!effectiveReadOnly"/)
  assert.doesNotMatch(baseNode, /v-if="selected && !effectiveReadOnly"/)
  assert.match(baseNode, /focus-within/)
  assert.match(nodeControl, /:disabled="disabled"/)
})

test('node handles expose a keyboard-accessible add action', () => {
  assert.match(nodeHandle, /button/)
  assert.match(nodeHandle, /:aria-label="addAction\.ariaLabel"/)
  assert.match(nodeHandle, /@click="handleAddNode"/)
  assert.match(nodeHandle, /\.node-handle-plus:focus-visible/)
})

test('BaseNode keeps Dify dimensions and state selectors', () => {
  assert.match(baseNode, /width:\s*240px/)
  assert.match(baseNode, /border-radius:\s*16px/)
  assert.match(baseNode, /is-plugin-missing/)
  assert.match(baseNode, /is-candidate/)
})

test('container nodes expose an in-canvas resizer with safe minimum dimensions', () => {
  assert.equal(existsSync(containerResizerUrl), true)
  const containerResizer = readFileSync(containerResizerUrl, 'utf8')
  assert.match(baseNode, /ContainerResizer/)
  assert.match(baseNode, /v-if="isContainer && selected && !effectiveReadOnly"/)
  assert.match(containerResizer, /CONTAINER_MIN_WIDTH/)
  assert.match(containerResizer, /CONTAINER_MIN_HEIGHT/)
  assert.match(containerResizer, /getContainerFitSize/)
  assert.match(containerResizer, /updateNodeDimensions/)
})

test('knowledge retrieval is registered as a custom node instead of Vue Flow default', () => {
  assert.match(registry, /^\s*'knowledge-retrieval':\s*markRaw\(KnowledgeRetrievalNode\),/m)
})

test('variable writer and aggregator resolve to their official Dify components', () => {
  assert.match(registry, /^\s*assigner:\s*markRaw\(VariableAssignerNode\),/m)
  assert.match(registry, /^\s*'variable-assigner':\s*markRaw\(VariableAggregatorNode\),/m)
  assert.match(registry, /^\s*assigner:\s*markRaw\(VariableAssignerPanel\),/m)
  assert.match(registry, /^\s*'variable-assigner':\s*markRaw\(VariableAggregatorPanel\),/m)
})

test('variable aggregator uses the official type and an empty Dify-compatible default', () => {
  assert.match(blockSelectorMenu, /'variable-assigner':\s*'聚合变量'/)
  assert.match(variableAggregatorPanel, /BlockIcon type="variable-assigner"/)
  assert.match(variableAggregatorPanel, /value="any"/)
  assert.match(variableAggregatorConfig, /variables \|\| \[\]/)
  assert.match(variableAggregatorConfig, /output_type \|\| 'any'/)
  assert.doesNotMatch(variableAggregatorConfig, /llm1|llm2/)
})

test('canvas grows containers after child dimensions are measured', () => {
  assert.match(workflowCanvas, /@nodes-change="handleNodesChange"/)
  assert.match(workflowCanvas, /getContainerFitSize/)
})
