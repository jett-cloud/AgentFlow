<template>
  <div
    class="note-node"
    :class="[`theme-${data.theme || 'blue'}`, { selected }]"
    :style="{ width: `${data.width || 240}px`, height: `${data.height || 88}px` }"
  >
    <NoteResizer
      v-if="selected && !effectiveReadOnly"
      :node-id="id"
      :data="data"
    />
    <div class="note-strip"></div>
    <div v-if="selected && !effectiveReadOnly" class="note-toolbar nodrag">
      <button
        v-for="theme in themes"
        :key="theme"
        type="button"
        :aria-label="`切换为${theme}主题`"
        :class="[`theme-${theme}`, { active: data.theme === theme }]"
        @click="updateTheme(theme)"
      ></button>
      <span class="toolbar-separator" aria-hidden="true"></span>
      <button
        type="button"
        class="toolbar-action"
        aria-label="显示作者"
        :aria-pressed="Boolean(data.showAuthor)"
        :title="data.showAuthor ? '隐藏作者' : '显示作者'"
        @click="toggleAuthor"
      >作</button>
      <button type="button" class="toolbar-action" aria-label="复制便签" title="复制" @click="copyNote">⎘</button>
      <button type="button" class="toolbar-action" aria-label="创建便签副本" title="创建副本" @click="duplicateNote">+</button>
      <button type="button" aria-label="删除便签" class="delete-note" @click="core?.removeNode?.(id)">×</button>
    </div>
    <textarea
      v-model="draftText"
      class="note-editor nodrag nowheel"
      name="workflow-note"
      autocomplete="off"
      placeholder="写下备注…"
      :readonly="effectiveReadOnly"
      @blur="commitText"
    ></textarea>
    <div v-if="data.showAuthor && data.author" class="note-author">{{ data.author }}</div>
  </div>
</template>

<script setup>
import { computed, inject, ref, watch } from 'vue'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import NoteResizer from './NoteResizer.vue'
import {
  NOTE_THEMES,
  noteTextToPlainText,
  plainTextToNoteEditorState,
} from './noteNode.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})

const store = useWorkflowStore()
const core = inject('workflowCore', null)
const effectiveReadOnly = computed(() => props.readOnly || store.readOnly)
const themes = NOTE_THEMES
const draftText = ref(noteTextToPlainText(props.data.text))

watch(() => props.data.text, value => {
  const plainText = noteTextToPlainText(value)
  if (plainText !== draftText.value)
    draftText.value = plainText
})

function commitText() {
  if (effectiveReadOnly.value || draftText.value === noteTextToPlainText(props.data.text)) return
  core?.updateNodeData?.(props.id, { text: plainTextToNoteEditorState(draftText.value) })
}

function updateTheme(theme) {
  core?.updateNodeData?.(props.id, { theme })
}

function toggleAuthor() {
  core?.updateNodeData?.(props.id, { showAuthor: !props.data.showAuthor })
}

function copyNote() {
  core?.copyNode?.(props.id)
}

function duplicateNote() {
  core?.duplicateNode?.(props.id)
}
</script>

<style scoped>
.note-node {
  position: relative;
  display: flex;
  min-width: 240px;
  min-height: 88px;
  flex-direction: column;
  overflow: visible;
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 6px;
  background: var(--note-bg);
  color: #344054;
}

.note-node.selected {
  border-color: var(--note-border);
}

.note-strip {
  height: 8px;
  flex: none;
  border-radius: 5px 5px 0 0;
  background: var(--note-strip);
  opacity: 0.5;
}

.note-editor {
  min-height: 0;
  flex: 1;
  resize: none;
  border: 0;
  background: transparent;
  padding: 10px 12px;
  color: inherit;
  font: 12px/1.55 inherit;
}

.note-editor:focus-visible {
  outline: 2px solid var(--note-border);
  outline-offset: -2px;
}

.note-toolbar {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px;
  transform: translateX(-50%);
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
  border-radius: 9px;
  background: var(--components-panel-bg, #fff);
}

.note-toolbar button {
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 5px;
  background: var(--note-strip);
  cursor: pointer;
}

.note-toolbar button.active,
.note-toolbar button:focus-visible {
  outline: none;
  border-color: #101828;
}

.note-toolbar .delete-note {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: 3px;
  background: transparent;
  color: #d92d20;
}

.note-toolbar .toolbar-action {
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: #475467;
  font-size: 12px;
}

.toolbar-separator {
  width: 1px;
  height: 16px;
  margin: 0 2px;
  background: #eaecf0;
}

.note-author {
  padding: 0 12px 10px;
  color: #667085;
  font-size: 10px;
}

.theme-blue { --note-bg: #eff8ff; --note-strip: #b2ddff; --note-border: #53b1fd; }
.theme-cyan { --note-bg: #ecfdff; --note-strip: #a5f0fc; --note-border: #22ccee; }
.theme-green { --note-bg: #ecfdf3; --note-strip: #abefc6; --note-border: #47cd89; }
.theme-yellow { --note-bg: #fefbe8; --note-strip: #feee95; --note-border: #fac515; }
.theme-pink { --note-bg: #fdf2fa; --note-strip: #fcceee; --note-border: #ee46bc; }
.theme-violet { --note-bg: #f5f3ff; --note-strip: #ddd6fe; --note-border: #a78bfa; }
</style>
