import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const canvasDir = dirname(fileURLToPath(import.meta.url))
const srcDir = join(canvasDir, '..', '..', '..')
const frontendDir = join(srcDir, '..')
const plannerDockDir = join(srcDir, 'views', 'copilot', 'components', 'workflow-assist')

function source(relativePath) {
  return readFileSync(join(frontendDir, relativePath), 'utf8')
}

function productionSources(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.name === 'node_modules' || entry.name === 'dist')
      return []
    if (entry.isDirectory())
      return productionSources(path)
    if (!/\.(?:js|vue)$/.test(entry.name) || entry.name.endsWith('.test.js'))
      return []
    return [[path, readFileSync(path, 'utf8')]]
  })
}

test('WorkflowCanvas mounts the assistant Dock and never the planner Dock', () => {
  const canvas = source('src/features/workflow/canvas/WorkflowCanvas.vue')
  const page = source('src/features/workflow/pages/WorkflowPage.vue')

  assert.match(canvas, /@\/features\/workflow\/assistant\/WorkflowAssistDock\.vue/)
  assert.doesNotMatch(canvas, /views\/copilot\/components\/workflow-assist/)
  assert.match(canvas, /:sync-draft-if-dirty="syncDraftForAssist"/)
  assert.match(canvas, /@candidate-preview="handleWorkflowAssistCandidatePreview"/)
  assert.match(canvas, /assistPreviewing/)
  assert.doesNotMatch(canvas, /markDraftSaved\(\)[\s\S]{0,80}handleWorkflowAssistCandidatePreview/)
  assert.match(canvas, /if \(assistPreviewing\.value\)[\s\S]{0,80}return \{ hash: props\.draftHash \}/)
  assert.match(canvas, /isPreviewableAssistGraph/)
  assert.match(canvas, /restoreOfficialGraphIfPreviewing/)
  assert.match(canvas, /copy\.candidatePreviewNotice/)
  assert.match(canvas, /copy\.restoreDraft/)
  assert.match(canvas, /v-if="assistPreviewing"/)
  assert.match(canvas, /@click="restoreOfficialGraphIfPreviewing"/)
  assert.doesNotMatch(
    canvas,
    /function handleWorkflowAssistClose\(\) \{\s*restoreOfficialGraphIfPreviewing\(\)/,
  )
  assert.match(canvas, /:server-draft-hash="draftHash"/)
  assert.doesNotMatch(canvas, /:draft-hash="assistDraftRevision"/)
  assert.doesNotMatch(canvas, /:apply-hash="draftHash"/)
  assert.match(page, /:sync-draft-if-dirty="syncDraftBeforeRun"/)
  assert.match(page, /@assist-applied="handleWorkflowAssistApplied"/)
  assert.equal(existsSync(plannerDockDir), false)
})

test('production sources do not import the deleted planner workflow-assist directory', () => {
  for (const [path, contents] of productionSources(srcDir)) {
    assert.doesNotMatch(
      contents,
      /views\/copilot\/components\/workflow-assist/,
      path,
    )
  }
})
