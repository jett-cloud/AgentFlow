import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'
import { computed, ref } from 'vue'
import { buildWorkflowChecklist } from '../model/checklist.js'
import { buildDraftContentSignature } from '../model/draftSignature.js'
import {
  needsFollowUpSave,
  nextDraftStatusOnSignature,
  shouldRestartAutosaveTimer,
} from '../model/draftAutosave.js'
import { shouldFlushDraftOnLeave } from '../model/draftFlush.js'
import { graphToFlow } from '../model/dsl.js'
import { isChatflowMode } from '../model/appModes.js'

const { descriptor } = parse(readFileSync(new URL('./WorkflowCanvas.vue', import.meta.url), 'utf8'))
const { scriptSetupAst } = compileScript(descriptor, { id: 'checklist-regression' })
const setupSource = descriptor.scriptSetup.content
const checklistStart = scriptSetupAst.find(node => node.type === 'VariableDeclaration'
  && node.declarations.some(declaration => declaration.id.name === 'checklistIssues')).start
const checklistEnd = scriptSetupAst.find(node => node.type === 'FunctionDeclaration'
  && node.id.name === 'updateWorkflowName').start
const lifecycle = [
  'buildDraftPayload',
  'saveWorkflowDraft',
  'cancelPendingAutosave',
  'shouldFlushCurrentDraft',
  'flushDraftIfNeeded',
  'markDraftSaved',
  'initializeDraft',
].map((name) => {
  const node = scriptSetupAst.find(node => node.type === 'FunctionDeclaration' && node.id.name === name)
  return setupSource.slice(node.start, node.end)
}).join('\n')

// Execute the canvas's real initialization/polling code without Vue Flow's DOM
// measurement lifecycle. Validation, draft signatures, and Vue refs stay real.
function createCanvas() {
  const getNodes = ref([])
  const getEdges = ref([])
  const environmentVariables = ref([])
  const conversationVariables = ref([])
  const workflowName = ref('Checklist regression')
  const draftStatus = ref('saved')
  const assistPreviewing = ref(false)
  const saveDraftCalls = []
  const store = {
    ragPipelineVariables: [],
    setEnvironmentVariables: value => { environmentVariables.value = value },
    setConversationVariables: value => { conversationVariables.value = value },
    setRagPipelineVariables: value => { store.ragPipelineVariables = value },
  }
  const dependencies = {
    ref, computed, buildWorkflowChecklist, buildDraftContentSignature, isChatflowMode,
    shouldRestartAutosaveTimer, nextDraftStatusOnSignature, needsFollowUpSave, shouldFlushDraftOnLeave,
    getNodes, getEdges, environmentVariables, conversationVariables, workflowName,
    draftStatus, assistPreviewing, store,
    props: { workflowMode: 'workflow', appId: 'app-1' },
    draftUpdatedAt: ref(0), readOnly: ref(false), AUTOSAVE_DELAY_MS: 5000,
    setTimeout: () => 1, clearTimeout: () => {},
    nextTick: () => {}, clearRuntimeState: () => {}, refreshStartVariables: () => {},
    emit: (name, payload) => { if (name === 'save-draft') saveDraftCalls.push(payload) },
    exportGraph: () => ({ nodes: getNodes.value, edges: getEdges.value }),
    initFromGraph: (graph) => {
      const flow = graphToFlow(graph)
      getNodes.value = flow.nodes
      getEdges.value = flow.edges
    },
  }
  const load = new Function(...Object.keys(dependencies), `
    let autosaveTimer = null
    ${setupSource.slice(checklistStart, checklistEnd)}
    ${lifecycle}
    return { initializeDraft, pollDraftSignature, markDraftSaved, flushDraftIfNeeded,
      checklistIssues, checklistCount, getNodes, getEdges, assistPreviewing, draftStatus, props, store,
      pendingSave: () => autosaveTimer,
      setInFlightSignature: (value) => { inFlightSignature = value },
      readDraftSignature }
  `)
  return { ...load(...Object.values(dependencies)), saveDraftCalls }
}

function workflow({ missingModel = false } = {}) {
  return {
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      { id: 'llm', data: {
        type: 'llm', title: 'LLM',
        model: { provider: 'openai', name: missingModel ? '' : 'gpt-4o' },
        prompt_template: [{ role: 'user', text: 'Answer the question.' }],
      } },
      { id: 'end', data: { type: 'end', title: 'End', outputs: [
        { variable: 'text', value_selector: ['llm', 'text'], value_type: 'string' },
      ] } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm' },
      { id: 'e2', source: 'llm', target: 'end' },
    ],
  }
}

test('canvas shows checklist errors as soon as a draft loads without opening the panel', () => {
  const canvas = createCanvas()
  canvas.initializeDraft({ graph: workflow({ missingModel: true }) })
  assert.equal(canvas.checklistCount.value, 1)
  assert.equal(canvas.checklistIssues.value[0].id, 'model-config-llm')
})

test('closed checklist updates when node configuration changes and clears after repair', () => {
  const canvas = createCanvas()
  canvas.initializeDraft({ graph: workflow() })
  assert.equal(canvas.checklistCount.value, 0)
  canvas.getNodes.value.find(node => node.id === 'llm').data.model.name = ''
  // A save acknowledgement must not suppress a pending checklist refresh.
  canvas.markDraftSaved()
  canvas.pollDraftSignature()
  assert.equal(canvas.checklistCount.value, 1)
  canvas.getNodes.value.find(node => node.id === 'llm').data.model.name = 'gpt-4o'
  canvas.pollDraftSignature()
  assert.equal(canvas.checklistCount.value, 0)
})

test('candidate preview updates checklist without scheduling a draft save', () => {
  const canvas = createCanvas()
  canvas.initializeDraft({ graph: workflow() })
  canvas.assistPreviewing.value = true
  canvas.getNodes.value.find(node => node.id === 'llm').data.model.name = ''
  canvas.pollDraftSignature()
  assert.equal(canvas.checklistCount.value, 1)
  assert.equal(canvas.draftStatus.value, 'saved')
  assert.equal(canvas.pendingSave(), null)
})

test('unchanged graph and Vue Flow layout noise preserve the checklist snapshot', () => {
  const canvas = createCanvas()
  canvas.initializeDraft({ graph: workflow({ missingModel: true }) })
  const issues = canvas.checklistIssues.value
  canvas.getNodes.value[0].dimensions = { width: 240, height: 100 }
  canvas.getNodes.value[0].selected = true
  canvas.getNodes.value[0].data._running = true
  canvas.pollDraftSignature()
  assert.equal(canvas.checklistIssues.value, issues)
})

test('leaving while a save is in flight still persists later edits', () => {
  const canvas = createCanvas()
  canvas.initializeDraft({ graph: workflow() })
  canvas.setInFlightSignature(canvas.readDraftSignature())
  canvas.draftStatus.value = 'saving'
  canvas.saveDraftCalls.length = 0

  assert.equal(canvas.flushDraftIfNeeded(), false)
  assert.equal(canvas.saveDraftCalls.length, 0)

  canvas.getNodes.value.find(node => node.id === 'llm').data.prompt_template = [
    { role: 'user', text: 'Edited during save' },
  ]
  assert.equal(canvas.flushDraftIfNeeded(), true)
  assert.equal(canvas.saveDraftCalls.length, 1)
  const llm = canvas.saveDraftCalls[0].graph.nodes.find(node => node.id === 'llm')
  assert.equal(llm.data.prompt_template[0].text, 'Edited during save')
})
