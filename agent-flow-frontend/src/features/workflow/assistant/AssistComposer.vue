<template>
  <form class="assist-composer" @submit.prevent="submit" @dragover.prevent @drop.prevent="onDrop">
    <div v-if="targetNodes.length" class="target-nodes">
      <span>{{ copy.localEdit }}</span>
      <button
        v-for="node in targetNodes"
        :key="node.id"
        type="button"
        :aria-label="`${copy.removeTarget}: ${node.title || node.id}`"
        :disabled="disabled"
        @click="emit('remove-target-node', node.id)"
      >
        {{ node.title || node.type || node.id }} ×
      </button>
    </div>

    <div class="composer-editor-wrap">
      <div
        ref="instructionRef"
        class="instruction-editor"
        role="textbox"
        :aria-label="copy.instructionLabel"
        aria-multiline="true"
        :aria-disabled="disabled"
        :contenteditable="disabled ? 'false' : 'plaintext-only'"
        :data-placeholder="copy.instructionPlaceholder"
        @input="onEditorInput"
        @keydown="onKeydown"
        @compositionstart="isComposing = true"
        @compositionend="finishComposition"
      />
      <div
        v-if="mentionOpen"
        class="mention-menu"
        role="listbox"
        :aria-label="copy.mentionMenu"
      >
        <template v-if="visibleMentionOptions.length">
          <div v-for="group in visibleMentionGroups" :key="group.kind" class="mention-group">
            <p class="mention-group-label">{{
              group.kind === 'node' ? copy.mentionNodes
                : group.kind === 'tool' ? copy.mentionTools
                  : copy.mentionDatasets
            }}</p>
            <button
              v-for="item in group.items"
              :key="`${item.kind}:${item.id}`"
              type="button"
              role="option"
              :class="['mention-option', { 'is-selected': isMentionSelected(item) }]"
              :aria-selected="isMentionSelected(item)"
              @mousedown.prevent="chooseMention(item)"
            >
              {{ item.label }}
            </button>
          </div>
        </template>
        <p v-else class="mention-empty">{{ copy.mentionEmpty }}</p>
      </div>
    </div>

    <div class="composer-footer">
      <ModelSelector
        ref="modelSelectorRef"
        :model-value="modelValue"
        :disabled="disabled"
        :placeholder="copy.selectModel"
        @update:model-value="emit('update:modelValue', $event)"
      />
      <div class="composer-actions">
        <button
          :type="running ? 'button' : 'submit'"
          :class="running ? 'stop-button' : 'send-button'"
          :disabled="running ? false : !canSend"
          :title="running ? copy.stopTitle : sendTitle"
          :aria-label="running ? copy.stop : copy.send"
          @click="handlePrimaryAction"
        >
          <VideoPause v-if="running" aria-hidden="true" />
          <Promotion v-else aria-hidden="true" />
        </button>
      </div>
    </div>
    <p v-if="awaitingClarification" class="hint">{{ copy.waitingHint }}</p>
    <p v-if="!hasModel" class="hint">{{ copy.modelRequired }}</p>
  </form>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Promotion, VideoPause } from '@element-plus/icons-vue'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'
import { useToolStore } from '@/features/integrations/state/useToolStore.js'
import ModelSelector from '../nodes/shared/ModelSelector.vue'
import { createAssistComposerSubmission } from './assistComposerSubmission.js'
import { assistCopy } from './assistLanguage.js'
import {
  ASSIST_MENTION_LIMIT,
  catalogMentionItems,
  detectMentionTrigger,
  filterMentionGroups,
  serializeMentionReferences,
} from './assistMentions.js'

const props = defineProps({
  disabled: { type: Boolean, default: false },
  running: { type: Boolean, default: false },
  awaitingClarification: { type: Boolean, default: false },
  language: { type: String, default: 'zh-Hans' },
  modelValue: {
    type: Object,
    default: () => ({ provider: '', name: '', mode: 'chat', completion_params: {} }),
  },
  targetNodes: { type: Array, default: () => [] },
  currentGraph: { type: Object, default: () => ({ nodes: [], edges: [] }) },
})

const emit = defineEmits(['send', 'update:modelValue', 'add-target-node', 'remove-target-node', 'cancel'])
const instructionRef = ref(null)
const modelSelectorRef = ref(null)
const hasEditorContent = ref(false)
const isComposing = ref(false)
const mentionOpen = ref(false)
const mentionQuery = ref('')
const mentionStart = ref(-1)
const mentionIndex = ref(0)
const cataloguesReady = ref(false)
const toolStore = useToolStore()
const datasetStore = useDatasetStore()
const copy = computed(() => assistCopy(props.language))
const hasModel = computed(() => Boolean(props.modelValue?.provider && props.modelValue?.name))
const canSend = computed(() => !props.disabled && hasModel.value && hasEditorContent.value)
const sendTitle = computed(() => (
  hasModel.value
    ? (props.awaitingClarification ? copy.value.sendAnswer : copy.value.sendInstruction)
    : copy.value.modelRequired
))
const mentionCatalog = computed(() => catalogMentionItems({
  nodes: props.currentGraph?.nodes || [],
  tools: toolStore.allTools || [],
  datasets: datasetStore.datasets || [],
}))
const mentionGroups = computed(() => filterMentionGroups(mentionCatalog.value, mentionQuery.value))
const visibleMentionGroups = computed(() => mentionGroups.value.filter(group => group.items.length))
const visibleMentionOptions = computed(() => visibleMentionGroups.value.flatMap(group => group.items))

const submission = createAssistComposerSubmission({
  readText: () => instructionRef.value?.innerText,
  readReferences: () => serializeMentionReferences(
    [...(instructionRef.value?.querySelectorAll('[data-assist-mention="true"]') || [])],
    mentionCatalog.value,
  ),
  clearText() {
    instructionRef.value?.replaceChildren()
    closeMentionMenu()
    syncEditorState()
  },
  emitSend: (message, receipt, references) => emit('send', message, receipt, references),
})

function submit() {
  if (!canSend.value)
    return
  closeMentionMenu()
  submission.submit()
}

function handlePrimaryAction() {
  if (props.running)
    emit('cancel')
}

function syncEditorState() {
  hasEditorContent.value = Boolean(String(instructionRef.value?.innerText || '').trim())
}

function onEditorInput() {
  syncEditorState()
  if (!isComposing.value)
    syncMentionTrigger()
}

function onKeydown(event) {
  if (mentionOpen.value)
    return handleMentionKeydown(event)
  if (!isComposing.value && event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    submit()
  }
}

function handleMentionKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeMentionMenu()
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    moveMentionSelection(1)
    return
  }
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    moveMentionSelection(-1)
    return
  }
  if (event.key === 'Enter' && !event.ctrlKey && !event.metaKey) {
    event.preventDefault()
    const item = visibleMentionOptions.value[mentionIndex.value]
    if (item)
      chooseMention(item)
  }
}

function finishComposition() {
  isComposing.value = false
  syncEditorState()
  syncMentionTrigger()
}

function isMentionSelected(item) {
  return visibleMentionOptions.value[mentionIndex.value] === item
}

function moveMentionSelection(delta) {
  const total = visibleMentionOptions.value.length
  if (!total)
    return
  mentionIndex.value = (mentionIndex.value + delta + total) % total
}

function syncMentionTrigger() {
  const root = instructionRef.value
  if (!root || props.disabled) {
    closeMentionMenu()
    return
  }
  const prefix = textBeforeCaret(root)
  const trigger = detectMentionTrigger(prefix)
  if (!trigger || existingMentionCount() >= ASSIST_MENTION_LIMIT) {
    closeMentionMenu()
    return
  }
  const previousQuery = mentionQuery.value
  mentionQuery.value = trigger.query
  mentionStart.value = trigger.start
  if (!mentionOpen.value || previousQuery !== trigger.query)
    mentionIndex.value = 0
  if (!mentionOpen.value) {
    mentionOpen.value = true
    ensureCatalogues()
  }
}

function closeMentionMenu() {
  mentionOpen.value = false
  mentionQuery.value = ''
  mentionStart.value = -1
  mentionIndex.value = 0
}

function existingMentionCount() {
  return instructionRef.value?.querySelectorAll('[data-assist-mention="true"]').length || 0
}

async function ensureCatalogues() {
  if (cataloguesReady.value)
    return
  cataloguesReady.value = true
  await Promise.all([
    toolStore.fetchTools(),
    datasetStore.loadDatasets({ limit: 50 }),
  ])
}

function chooseMention(item) {
  insertMentionItem(item, { replaceTrigger: true })
  closeMentionMenu()
  syncEditorState()
}

function insertMentionItem(item, { replaceTrigger }) {
  const root = instructionRef.value
  if (!root || !item || existingMentionCount() >= ASSIST_MENTION_LIMIT)
    return
  root.focus()
  const selection = window.getSelection()
  if (!selection)
    return
  if (replaceTrigger && mentionStart.value >= 0) {
    const prefix = textBeforeCaret(root)
    const range = rangeFromCharacterOffsets(root, mentionStart.value, prefix.length)
    if (range) {
      range.deleteContents()
      selection.removeAllRanges()
      selection.addRange(range)
    }
  }
  else if (!selection.rangeCount || !root.contains(selection.anchorNode)) {
    const end = document.createRange()
    end.selectNodeContents(root)
    end.collapse(false)
    selection.removeAllRanges()
    selection.addRange(end)
  }
  const range = selection.getRangeAt(0)
  range.deleteContents()
  const chip = createMentionChip(item)
  range.insertNode(document.createTextNode(' '))
  range.insertNode(chip)
  range.setStartAfter(chip.nextSibling || chip)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
}

function createMentionChip(item) {
  const chip = document.createElement('span')
  chip.contentEditable = 'false'
  chip.className = 'mention-chip'
  chip.dataset.resourceReference = 'true'
  chip.dataset.assistMention = 'true'
  chip.dataset.kind = item.kind
  chip.dataset.id = item.id
  if (item.kind === 'tool') {
    chip.dataset.provider = item.provider || ''
    chip.dataset.toolName = item.tool_name || ''
  }
  chip.textContent = item.label
  return chip
}

function textBeforeCaret(root) {
  const selection = window.getSelection()
  if (!selection?.rangeCount)
    return ''
  const caret = selection.getRangeAt(0)
  if (!root.contains(caret.startContainer))
    return ''
  const prefix = document.createRange()
  prefix.selectNodeContents(root)
  prefix.setEnd(caret.startContainer, caret.startOffset)
  return prefix.toString()
}

function rangeFromCharacterOffsets(root, start, end) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let count = 0
  let startNode
  let startOffset = 0
  let endNode
  let endOffset = 0
  let node = walker.nextNode()
  while (node) {
    const next = count + node.data.length
    if (!startNode && start <= next) {
      startNode = node
      startOffset = Math.max(0, start - count)
    }
    if (end <= next) {
      endNode = node
      endOffset = Math.max(0, end - count)
      break
    }
    count = next
    node = walker.nextNode()
  }
  if (!startNode || !endNode)
    return null
  const range = document.createRange()
  range.setStart(startNode, startOffset)
  range.setEnd(endNode, endOffset)
  return range
}

function onDrop(event) {
  if (props.disabled)
    return
  const raw = event.dataTransfer?.getData('application/x-workflow-assist-node')
  if (!raw)
    return
  try {
    const node = JSON.parse(raw)
    if (node?.id)
      emit('add-target-node', node)
  }
  catch {
    // Ignore unrelated drag payloads.
  }
}

function insertResource(resource) {
  if (!instructionRef.value || !resource)
    return
  const item = resource.kind && resource.id
    ? resource
    : catalogMentionItems({
      nodes: resource.id && !resource.tool_name && !resource.provider_name ? [resource] : [],
      tools: resource.tool_name ? [resource] : [],
      datasets: resource.kind === 'dataset' || resource.name ? [resource] : [],
    })[0]
  if (!item)
    return
  insertMentionItem(item, { replaceTrigger: false })
  syncEditorState()
}

function focusInstruction() {
  instructionRef.value?.focus()
}

function focusModelSelector() {
  modelSelectorRef.value?.focus?.()
}

defineExpose({ focusInstruction, focusModelSelector, insertResource })
</script>

<style scoped>
.assist-composer {
  display: grid;
  gap: 10px;
  padding: 12px;
  border-top: 1px solid #e4e7ec;
  background: #fff;
}

.target-nodes {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: #475467;
  font-size: 12px;
}

.target-nodes button {
  border: 1px solid #d0d5dd;
  border-radius: 999px;
  background: #f9fafb;
  color: #344054;
}

.composer-editor-wrap {
  position: relative;
}

.instruction-editor {
  min-height: 82px;
  overflow-y: auto;
  border: 1px solid #d0d5dd;
  border-radius: 10px;
  padding: 10px 12px;
  color: #101828;
  font: inherit;
  line-height: 1.5;
}

.instruction-editor:empty::before {
  color: #98a2b3;
  content: attr(data-placeholder);
  pointer-events: none;
}

.instruction-editor:focus-visible,
.target-nodes button:focus-visible,
.composer-actions button:focus-visible,
.mention-option:focus-visible {
  outline: 2px solid #175cd3;
  outline-offset: 2px;
}

.instruction-editor :deep(.mention-chip) {
  display: inline-flex;
  align-items: center;
  margin: 0 1px;
  border: 1px solid #d0d5dd;
  border-radius: 999px;
  background: #f9fafb;
  padding: 0 8px;
  color: #175cd3;
  font-size: 12px;
  line-height: 1.6;
  user-select: none;
}

.mention-menu {
  position: absolute;
  right: 0;
  bottom: 100%;
  left: 0;
  z-index: 40;
  max-height: 280px;
  overflow: auto;
  border: 1px solid #d0d5dd;
  border-radius: 12px;
  margin-bottom: 6px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(16 24 40 / 8%);
}

.mention-group-label,
.mention-empty {
  margin: 0;
  padding: 8px 12px 4px;
  color: #667085;
  font-size: 12px;
}

.mention-option {
  display: block;
  width: 100%;
  border: 0;
  background: transparent;
  padding: 8px 12px;
  color: #101828;
  text-align: left;
  cursor: pointer;
}

.mention-option.is-selected {
  background: #175cd3;
  color: #fff;
}

.composer-footer,
.composer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.composer-footer {
  justify-content: space-between;
}

.composer-actions button {
  display: inline-flex;
  width: 34px;
  min-height: 34px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  padding: 0;
  cursor: pointer;
}

.composer-actions button :deep(svg) {
  width: 16px;
  height: 16px;
}

.stop-button {
  border: 1px solid #fda29b;
  background: #fff;
  color: #b42318;
}

.send-button {
  border: 1px solid #175cd3;
  background: #175cd3;
  color: #fff;
}

.send-button:disabled {
  border-color: #d0d5dd;
  background: #eaecf0;
  color: #98a2b3;
  cursor: not-allowed;
}

.hint {
  margin: 0;
  color: #667085;
  font-size: 12px;
  line-height: 1.4;
}

@media (prefers-reduced-motion: reduce) {
  .instruction-editor,
  .composer-actions button,
  .mention-menu {
    scroll-behavior: auto;
    transition: none;
  }
}
</style>
