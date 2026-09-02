import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const assistantDir = dirname(fileURLToPath(import.meta.url))
const srcDir = join(assistantDir, '..', '..', '..')
const frontendDir = join(srcDir, '..')

function source(relativePath) {
  return readFileSync(join(frontendDir, relativePath), 'utf8')
}

function productionSources(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory())
      return productionSources(path)
    if (!/\.(?:js|vue)$/.test(entry.name) || entry.name.endsWith('.test.js'))
      return []
    return [[path, readFileSync(path, 'utf8')]]
  })
}

test('the real WorkflowCanvas mount path imports only the canonical recoverable Dock', () => {
  const canvas = source('src/features/workflow/canvas/WorkflowCanvas.vue')
  const page = source('src/features/workflow/pages/WorkflowPage.vue')
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')

  assert.match(canvas, /@\/features\/workflow\/assistant\/WorkflowAssistDock\.vue/)
  assert.match(canvas, /:sync-draft-if-dirty="syncDraftForAssist"/)
  assert.match(canvas, /@candidate-preview="handleWorkflowAssistCandidatePreview"/)
  assert.match(page, /:sync-draft-if-dirty="syncDraftBeforeRun"/)
  assert.match(page, /@assist-applied="handleWorkflowAssistApplied"/)
  assert.match(dock, /emit\('candidate-preview'/)
  assert.match(dock, /candidateStale/)
  assert.match(dock, /serverDraftHash/)
  assert.doesNotMatch(dock, /resumeActiveTurn\(/)
  assert.doesNotMatch(source('src/features/workflow/assistant/useWorkflowAssistController.js'), /streamChat/)
})

test('canonical Dock exposes explicit stop, detached close, and authoritative apply states', () => {
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')

  assert.match(dock, /stopActiveTurn/)
  assert.match(dock, /detachActiveTurn/)
  assert.match(dock, /workflowAssistApplyPresentation/)
  assert.match(dock, /applyWorkflowAssistCandidate/)
  assert.match(dock, /applying/)
  assert.match(dock, /:aria-busy="applying"/)
})

test('Apply visibility is independent from its in-flight disabled state in the real Dock SFC', () => {
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')

  assert.match(dock, /v-if="applyUi\.visible"/)
  assert.match(dock, /:disabled="applyUi\.disabled"/)
  assert.match(dock, /:disabled="applyUi\.disabled"[\s\S]{0,120}:aria-busy="applying"/)
  assert.match(dock, /applying \? copy\.applying : copy\.apply/)
  assert.doesNotMatch(dock, /v-if="canApply"/)
})

test('the real Dock SFC owns a distinct deduplicated Run and Apply status live region', () => {
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')

  assert.match(dock, /createAssistStatusAnnouncement/)
  assert.match(dock, /class="[^\"]*assist-status-announcement[^\"]*"/)
  assert.match(dock, /aria-live="polite"/)
  for (const status of ['queued', 'running', 'waiting_user', 'done', 'failed', 'error', 'aborted', 'turn_complete'])
    assert.match(dock, new RegExp(`['\"]${status}['\"]`))
  assert.match(dock, /statusApplyApplying/)
  assert.match(dock, /statusApplyApplied/)
  assert.match(dock, /statusApplyConflict/)
  assert.match(dock, /statusApplyFailed/)
  assert.match(dock, /onRunStatus:\s*announceRunStatus/)
  assert.doesNotMatch(dock, /event\?\.type === 'SEND'[\s\S]{0,120}announceRunStatus\('queued'\)/)
})

test('the canonical Composer leaves native paste and undo behavior to the browser', () => {
  const composer = source('src/features/workflow/assistant/AssistComposer.vue')

  assert.doesNotMatch(composer, /@paste=/)
  assert.doesNotMatch(composer, /function onPaste/)
  assert.doesNotMatch(composer, /execCommand|clipboardData|preventDefault\(\)[\s\S]*paste/)
  assert.match(composer, /@input="onEditorInput"/)
})

test('the Composer exposes one primary action that switches between send and stop', () => {
  const composer = source('src/features/workflow/assistant/AssistComposer.vue')
  const actions = composer.match(/<div class="composer-actions">([\s\S]*?)<\/div>/)?.[1] || ''

  assert.equal((actions.match(/<button\b/g) || []).length, 1)
  assert.match(actions, /:class="running \? 'stop-button' : 'send-button'"/)
  assert.match(actions, /:type="running \? 'button' : 'submit'"/)
  assert.match(actions, /@click="handlePrimaryAction"/)
  assert.match(actions, /<VideoPause v-if="running"[^>]*\/>/)
  assert.match(actions, /<Promotion v-else[^>]*\/>/)
  assert.match(actions, /:aria-label="running \? copy\.stop : copy\.send"/)
  assert.doesNotMatch(actions, /\{\{ copy\.(?:stop|send) \}\}/)
  assert.match(composer, /import \{ Promotion, VideoPause \} from '@element-plus\/icons-vue'/)
  assert.match(composer, /function handlePrimaryAction\(\)/)
})

test('Assist copy, live announcements, keyboard controls, and reduced motion are explicit', () => {
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')
  const composer = source('src/features/workflow/assistant/AssistComposer.vue')
  const list = source('src/features/workflow/assistant/AssistMessageList.vue')
  const card = source('src/features/workflow/assistant/AssistClarificationCard.vue')

  for (const content of [dock, composer, list, card]) {
    assert.match(content, /assistCopy/)
    assert.doesNotMatch(content, />\s*[\u3400-\u9fff][^<]*</u)
  }
  assert.match(list, /class="[^"]*assist-live-announcement[^"]*"/)
  assert.match(list, /aria-live="polite"/)
  assert.doesNotMatch(list, /assist-message-list" aria-live=/)
  assert.match(card, /<form[^>]*@submit\.prevent=/)
  assert.match(card, /<button[^>]*type="submit"/)
  assert.match(list, /renderMarkdown/)
  assert.match(list, /stripAssistToolJson/)
  assert.match(list, /AssistClarificationCard/)
  assert.match(dock, /@media \(prefers-reduced-motion: reduce\)/)
  assert.match(composer, /@media \(prefers-reduced-motion: reduce\)/)
})

test('clarification card uses studio chips and optional other without a duplicate legend', () => {
  const card = source('src/features/workflow/assistant/AssistClarificationCard.vue')

  assert.match(card, /class="chip/)
  assert.match(card, /copy\.other/)
  assert.match(card, /min-height:\s*32px/)
  assert.match(card, /#175cd3/)
  assert.match(card, /shouldSubmitOnChipClick/)
  assert.doesNotMatch(card, /<legend/)
})

test('Dock resize cleanup and narrow history content have symmetric observable contracts', () => {
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')

  assert.match(dock, /removeEventListener\('pointermove', resizeDock\)/)
  assert.match(dock, /removeEventListener\('pointerup', stopDockResize\)/)
  assert.match(dock, /<time[^>]*:datetime="conversation\.updated_at"/)
  assert.match(dock, /formatConversationTimestamp\(conversation\.updated_at\)/)
  assert.match(dock, /class="history-title"/)
  assert.match(dock, /class="history-time"/)
  assert.match(dock, /\.history-title\s*\{[^}]*min-width:\s*0;[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis;/s)
  assert.match(dock, /\.history-time\s*\{[^}]*flex-shrink:\s*0;/s)
})

test('left dock exposes its resize handle on the canvas boundary and follows pointer movement', () => {
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')

  assert.match(dock, /\.dock-resize-handle\s*\{[^}]*inset:\s*0 -4px 0 auto;[^}]*cursor:\s*ew-resize;/s)
  assert.doesNotMatch(dock, /\.dock-resize-handle\s*\{[^}]*left:\s*-4px;/s)
  assert.match(dock, /assistStore\.setPanelWidth\(resizeStart\.width \+ \(event\.clientX - resizeStart\.x\)\)/)
})

test('legacy implementation and v1 protocol symbols are absent from production', () => {
  const legacy = join(srcDir, 'views', 'copilot', 'components', 'workflow-assist')
  assert.equal(existsSync(legacy), false)

  const forbidden = /chat\/stream|plan\/stream|generate\/stream|EventSource|streamWorkflowAssist(?:Chat|Plan|Generate)|postWorkflowAssist(?:ChatAbort|Plan|Generate|Validate|Hydrate)|updateWorkflowAssistConversation/
  const matches = productionSources(srcDir)
    .filter(([, content]) => forbidden.test(content))
    .map(([path]) => path)
  assert.deepEqual(matches, [])
})

test('every canonical local component import resolves after legacy deletion', () => {
  const missing = []
  for (const [path, content] of productionSources(assistantDir)) {
    for (const match of content.matchAll(/from ['"]\.\/([^'"]+)['"]/g)) {
      const target = join(dirname(path), match[1])
      if (!existsSync(target) || !statSync(target).isFile())
        missing.push(`${path} -> ${match[1]}`)
    }
  }
  assert.deepEqual(missing, [])
})

test('the Composer opens a grouped @ mention menu and serializes chips on send', () => {
  const composer = source('src/features/workflow/assistant/AssistComposer.vue')
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')

  assert.match(composer, /class="mention-menu"/)
  assert.match(composer, /copy\.mentionNodes/)
  assert.match(composer, /copy\.mentionTools/)
  assert.match(composer, /copy\.mentionDatasets/)
  assert.match(composer, /detectMentionTrigger/)
  assert.match(composer, /serializeMentionReferences/)
  assert.match(composer, /readReferences/)
  assert.match(composer, /currentGraph/)
  assert.match(composer, /useToolStore/)
  assert.match(composer, /useDatasetStore/)
  assert.match(composer, /border-radius:\s*12px/)
  assert.match(composer, /background:\s*#175cd3/)
  assert.match(composer, /bottom:\s*100%/)
  assert.match(dock, /:current-graph="currentGraph"/)
  assert.match(dock, /selected_node/)
  assert.match(dock, /turn\.references/)
})

test('conversation history can delete a row without selecting it', () => {
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')
  const language = source('src/features/workflow/assistant/assistLanguage.js')

  assert.match(dock, /deleteWorkflowAssistConversation/)
  assert.match(dock, /copy\.deleteConversation/)
  assert.match(dock, /copy\.value\.confirmDeleteConversation/)
  assert.match(dock, /@click\.stop/)
  assert.match(dock, /nextConversationIdAfterDelete/)
  assert.match(language, /deleteConversation: 'Delete conversation'/)
  assert.match(language, /deleteConversation: '删除会话'/)
  assert.doesNotMatch(dock, />\s*删除会话\s*</)
})

test('closing the assistant keeps the candidate preview until Apply or restore draft', () => {
  const language = source('src/features/workflow/assistant/assistLanguage.js')
  const canvas = source('src/features/workflow/canvas/WorkflowCanvas.vue')

  assert.match(language, /restoreDraft: 'Restore draft'/)
  assert.match(language, /restoreDraft: '恢复草稿'/)
  assert.match(language, /Apply to save it as the draft/)
  assert.doesNotMatch(language, /Close the assistant to return to the draft/)
  assert.doesNotMatch(language, /关闭助手会回到当前草稿/)
  assert.match(canvas, /copy\.restoreDraft/)
})

test('conversation history can rename a row without selecting it', () => {
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')
  const language = source('src/features/workflow/assistant/assistLanguage.js')
  const api = source('src/features/workflow/api/difyWorkflowAssistApi.js')

  assert.match(dock, /patchWorkflowAssistConversationTitle/)
  assert.match(dock, /copy\.renameConversation/)
  assert.match(dock, /@dblclick\.stop/)
  assert.match(dock, /normalizeConversationTitle/)
  assert.match(api, /patchWorkflowAssistConversationTitle/)
  assert.match(language, /renameConversation: 'Rename conversation'/)
  assert.match(language, /renameConversation: '重命名会话'/)
  assert.doesNotMatch(dock, />\s*重命名会话\s*</)
  assert.doesNotMatch(api, /updateWorkflowAssistConversation/)
})

test('retryable failures expose Retry this step and call the retry API', () => {
  const dock = source('src/features/workflow/assistant/WorkflowAssistDock.vue')
  const list = source('src/features/workflow/assistant/AssistMessageList.vue')
  const controller = source('src/features/workflow/assistant/useWorkflowAssistController.js')

  assert.match(dock, /postWorkflowAssistRunRetry/)
  assert.match(dock, /retryFailedStep/)
  assert.match(dock, /:retryable="session\.retryable"/)
  assert.match(list, /copy\.retryThisStep/)
  assert.match(list, /v-if="retryable"/)
  assert.match(controller, /failed_step_id/)
  assert.doesNotMatch(list, />\s*重试此步\s*</)
})
