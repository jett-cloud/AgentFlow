<!--
  Prompt 文本框：敲 `{` 弹出可用变量菜单，插入 {{#nodeId.var#}}。
  也支持工具栏「插入变量」按钮（不依赖 Lexical）。
-->
<template>
  <div class="prompt-var-field" ref="rootRef">
    <div v-if="showToolbar" class="field-toolbar">
      <button
        type="button"
        class="insert-btn"
        :disabled="disabled || readOnly"
        @mousedown.prevent="openMenuFromToolbar"
      >
        {'{ }'} 插入变量
      </button>
      <span class="hint">输入 <code>{</code> 也可选择变量</span>
    </div>

    <textarea
      ref="textareaRef"
      class="prompt-textarea"
      :value="modelValue"
      :rows="rows"
      :disabled="disabled || readOnly"
      :placeholder="placeholder"
      @input="onInput"
      @keydown="onKeydown"
      @click="syncTriggerFromCaret"
      @keyup="syncTriggerFromCaret"
      @blur="onBlur"
    />

    <div
      v-if="menuOpen"
      class="var-menu"
      role="listbox"
      @mousedown.prevent
    >
      <div class="var-menu-search">
        <input
          ref="searchRef"
          v-model="filterQuery"
          type="text"
          placeholder="搜索变量"
          @keydown="onMenuKeydown"
        />
      </div>
      <div v-if="filteredGroups.length" class="var-menu-body">
        <div v-for="group in filteredGroups" :key="group.nodeId" class="var-group">
          <div class="var-group-title">{{ group.title }}</div>
          <div
            v-for="(row, idx) in group.rows"
            :key="`${group.nodeId}.${row.key}`"
            class="var-option-wrap"
            @mouseenter="onEnterRow(group, row, idx)"
            @mouseleave="onLeaveRow"
          >
            <button
              type="button"
              class="var-option"
              :class="{ active: isActiveOption(group.nodeId, idx) }"
              @click="selectVar(group.nodeId, row.selectorPath)"
            >
              <span class="var-name">{{ row.displayPath }}</span>
              <span class="var-type">{{ row.type }}</span>
              <span v-if="row.hasChildren && !isSearching" class="chevron">›</span>
            </button>
            <ObjectChildTreePanel
              v-if="!isSearching && row.hasChildren && hoverKey === rowKey(group, row)"
              class="nested-panel"
              :root="{
                nodeId: group.nodeId,
                nodeName: group.title,
                attrName: row.displayPath,
                attrAlias: row.type,
              }"
              :children="row.children"
              :root-path="row.rootPath"
              @hovering="onNestedHovering"
              @select="onTreeSelect"
            />
          </div>
        </div>
      </div>
      <div v-else class="var-empty">没有匹配的变量</div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useAvailableVariables } from '../../model/useAvailableVariables.js'
import {
  flattenVarsForPicker,
  getVariableDisplayName,
  toValueSelectorFromPath,
} from '../../model/availableVariables.js'
import {
  getRootSelectorPath,
  hasNestedChildren,
} from '../../model/objectChildTree.js'
import {
  detectBraceTrigger,
  formatWorkflowVarToken,
  insertAtRange,
} from '../../model/promptVariableSyntax.js'
import ObjectChildTreePanel from './ObjectChildTreePanel.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  nodeId: { type: String, required: true },
  rows: { type: Number, default: 4 },
  placeholder: {
    type: String,
    default: '输入提示词，敲 { 插入变量…',
  },
  disabled: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
  showToolbar: { type: Boolean, default: true },
  filterVar: { type: Function, default: null },
})

const emit = defineEmits(['update:modelValue', 'change'])

const { availableVarGroups } = useAvailableVariables(() => props.nodeId, {
  filterVar: computed(() => props.filterVar),
})

const rootRef = ref(null)
const textareaRef = ref(null)
const searchRef = ref(null)
const menuOpen = ref(false)
const filterQuery = ref('')
const triggerRange = ref(null) // { start, end }
const activeFlatIndex = ref(0)
const blurTimer = ref(null)
const hoverKey = ref('')
const nestedHovering = ref(false)
let leaveTimer = null

const isSearching = computed(() => String(filterQuery.value || '').trim().length > 0)

const filteredGroups = computed(() => {
  const q = String(filterQuery.value || '').trim().toLowerCase()
  if (q) {
    const flattened = availableVarGroups.value.map(group => ({
      nodeId: group.nodeId,
      title: group.title,
      rows: flattenVarsForPicker(group.vars)
        .filter(row => (
          row.displayPath.toLowerCase().includes(q)
          || String(row.variable || '').toLowerCase().includes(q)
          || String(row.type || '').toLowerCase().includes(q)
          || String(row.des || '').toLowerCase().includes(q)
        ))
        .map(row => ({
          key: row.displayPath,
          displayPath: row.displayPath,
          type: row.type,
          selectorPath: row.selectorPath,
          hasChildren: false,
          children: null,
          rootPath: row.selectorPath,
        })),
    })).filter(group => group.rows.length)
    return flattened
  }

  return availableVarGroups.value.map(group => ({
    nodeId: group.nodeId,
    title: group.title,
    rows: (group.vars || []).map((variable) => {
      const rootPath = getRootSelectorPath(variable)
      return {
        key: variable.variable,
        displayPath: getVariableDisplayName(variable.variable),
        type: variable.type,
        selectorPath: rootPath,
        hasChildren: hasNestedChildren(variable),
        children: variable.children,
        rootPath,
        variable: variable.variable,
      }
    }),
  })).filter(group => group.rows.length)
})

const flatOptions = computed(() => {
  const list = []
  for (const group of filteredGroups.value) {
    group.rows.forEach((row, idx) => {
      list.push({
        nodeId: group.nodeId,
        variable: row.variable,
        selectorPath: row.selectorPath,
        groupIndex: idx,
      })
    })
  }
  return list
})

watch(filteredGroups, () => {
  activeFlatIndex.value = 0
})

function emitValue(text) {
  emit('update:modelValue', text)
  emit('change', text)
}

function openMenu(range, query = '', { focusSearch = false } = {}) {
  clearTimeout(blurTimer.value)
  triggerRange.value = range
  filterQuery.value = query
  menuOpen.value = true
  activeFlatIndex.value = 0
  if (focusSearch)
    nextTick(() => searchRef.value?.focus?.())
}

function closeMenu() {
  menuOpen.value = false
  triggerRange.value = null
  filterQuery.value = ''
}

function syncTriggerFromCaret() {
  const el = textareaRef.value
  if (!el || props.readOnly || props.disabled)
    return
  const trigger = detectBraceTrigger(el.value, el.selectionStart)
  if (!trigger) {
    if (menuOpen.value)
      closeMenu()
    return
  }
  openMenu(
    { start: trigger.start, end: el.selectionStart },
    trigger.query,
  )
}

function onInput(event) {
  const value = event.target.value
  emitValue(value)
  nextTick(() => syncTriggerFromCaret())
}

function onKeydown(event) {
  if (!menuOpen.value)
    return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeMenu()
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeFlatIndex.value = Math.min(activeFlatIndex.value + 1, Math.max(flatOptions.value.length - 1, 0))
    return
  }
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeFlatIndex.value = Math.max(activeFlatIndex.value - 1, 0)
    return
  }
  if (event.key === 'Enter' && flatOptions.value.length) {
    event.preventDefault()
    const opt = flatOptions.value[activeFlatIndex.value]
    if (opt)
      selectVar(opt.nodeId, opt.selectorPath)
  }
}

function onMenuKeydown(event) {
  onKeydown(event)
}

function onBlur(event) {
  if (rootRef.value?.contains(event.relatedTarget))
    return
  blurTimer.value = setTimeout(() => closeMenu(), 180)
}

function openMenuFromToolbar() {
  clearTimeout(blurTimer.value)
  const el = textareaRef.value
  if (!el)
    return
  el.focus()
  const caret = el.selectionStart ?? props.modelValue.length
  const { text, caret: nextCaret } = insertAtRange(props.modelValue, caret, caret, '{')
  emitValue(text)
  nextTick(() => {
    el.setSelectionRange(nextCaret, nextCaret)
    openMenu({ start: caret, end: nextCaret }, '', { focusSearch: true })
  })
}

function selectVar(nodeId, selectorPath) {
  const token = formatWorkflowVarToken(toValueSelectorFromPath(nodeId, selectorPath))
  const el = textareaRef.value
  const range = triggerRange.value || {
    start: el?.selectionStart ?? props.modelValue.length,
    end: el?.selectionEnd ?? props.modelValue.length,
  }
  const { text, caret } = insertAtRange(props.modelValue, range.start, range.end, token)
  emitValue(text)
  closeMenu()
  hoverKey.value = ''
  nestedHovering.value = false
  nextTick(() => {
    if (!el)
      return
    el.focus()
    el.setSelectionRange(caret, caret)
  })
}

function onTreeSelect(selector) {
  const token = formatWorkflowVarToken(selector)
  const el = textareaRef.value
  const range = triggerRange.value || {
    start: el?.selectionStart ?? props.modelValue.length,
    end: el?.selectionEnd ?? props.modelValue.length,
  }
  const { text, caret } = insertAtRange(props.modelValue, range.start, range.end, token)
  emitValue(text)
  closeMenu()
  hoverKey.value = ''
  nestedHovering.value = false
  nextTick(() => {
    if (!el)
      return
    el.focus()
    el.setSelectionRange(caret, caret)
  })
}

function rowKey(group, row) {
  return `${group.nodeId}::${row.key}`
}

function onEnterRow(group, row, idx) {
  clearTimeout(leaveTimer)
  hoverKey.value = rowKey(group, row)
  setActiveByIds(group.nodeId, idx)
}

function onLeaveRow() {
  leaveTimer = setTimeout(() => {
    if (!nestedHovering.value)
      hoverKey.value = ''
  }, 120)
}

function onNestedHovering(value) {
  nestedHovering.value = value
  if (value) {
    clearTimeout(leaveTimer)
    return
  }
  leaveTimer = setTimeout(() => {
    hoverKey.value = ''
  }, 120)
}

function isActiveOption(nodeId, idxInGroup) {
  const opt = flatOptions.value[activeFlatIndex.value]
  return opt && opt.nodeId === nodeId && opt.groupIndex === idxInGroup
}

function setActiveByIds(nodeId, idxInGroup) {
  const index = flatOptions.value.findIndex(item => item.nodeId === nodeId && item.groupIndex === idxInGroup)
  if (index >= 0)
    activeFlatIndex.value = index
}
</script>

<style scoped>
.prompt-var-field {
  position: relative;
  width: 100%;
}

.field-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.insert-btn {
  padding: 4px 8px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  background: #fff;
  color: #344054;
  font-size: 11px;
  cursor: pointer;
}

.insert-btn:hover:not(:disabled) {
  background: #f2f4f7;
}

.insert-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.hint {
  color: #98a2b3;
  font-size: 11px;
}

.hint code {
  padding: 0 3px;
  border-radius: 3px;
  background: #f2f4f7;
  color: #155eef;
}

.prompt-textarea {
  box-sizing: border-box;
  width: 100%;
  min-height: 72px;
  padding: 8px 10px;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  color: #101828;
  font: 12px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
  resize: vertical;
}

.prompt-textarea:focus {
  outline: 2px solid rgba(0, 51, 255, 0.2);
  border-color: #0033ff;
}

.prompt-textarea:disabled {
  background: #f9fafb;
  color: #667085;
}

.var-menu {
  position: absolute;
  z-index: 30;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  max-height: 260px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #eaecf0;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(16 24 40 / 12%);
}

.var-menu-search {
  padding: 8px;
  border-bottom: 1px solid #f2f4f7;
}

.var-menu-search input {
  box-sizing: border-box;
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  font-size: 12px;
}

.var-menu-body {
  overflow: auto;
  padding: 6px;
}

.var-group-title {
  padding: 4px 6px;
  color: #667085;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
}

.var-option {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.var-option-wrap {
  position: relative;
}

.var-option .chevron {
  margin-left: 4px;
  color: #98a2b3;
}

.nested-panel {
  position: absolute;
  top: 0;
  left: calc(100% + 4px);
  z-index: 30;
}

.var-option:hover,
.var-option.active {
  background: #eff4ff;
}

.var-name {
  color: #155eef;
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.var-type {
  margin-left: auto;
  color: #98a2b3;
  font-size: 10px;
}

.var-empty {
  padding: 16px;
  color: #98a2b3;
  font-size: 12px;
  text-align: center;
}
</style>
