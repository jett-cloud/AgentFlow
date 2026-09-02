<!--
  变量引用选择器：顶层列表 + 悬停嵌套树（对齐 Dify VarReferenceVars）。
-->
<template>
  <div ref="rootRef" class="var-ref-picker" :class="{ disabled: disabled || readOnly, open }">
    <button
      type="button"
      class="trigger"
      :disabled="disabled || readOnly"
      @click="toggleOpen"
    >
      <span class="trigger-text" :class="{ placeholder: !displayText }">
        {{ displayText || placeholder }}
      </span>
      <span v-if="clearable && modelValue?.length && !disabled && !readOnly" class="clear" @click.stop="onClear">×</span>
      <span class="caret">▾</span>
    </button>

    <div v-if="open" class="dropdown" @mousedown.prevent>
      <div v-if="!pickerGroups.length" class="empty-hint">暂无可用变量</div>
      <div v-for="group in pickerGroups" :key="group.nodeId" class="group">
        <div class="group-title">{{ group.title }}</div>
        <div
          v-for="row in group.rows"
          :key="`${group.nodeId}:${row.variable}`"
          class="option-wrap"
          @mouseenter="onEnterOption(group, row)"
          @mouseleave="onLeaveOption"
        >
          <button
            type="button"
            class="option"
            :class="{ active: isSelected(row.selector), hovering: isHovering(group, row) }"
            @click="selectSelector(row.selector)"
          >
            <span class="var-name">{{ row.displayName }}</span>
            <span class="var-type">{{ row.type }}</span>
            <span v-if="row.hasChildren" class="chevron">›</span>
          </button>
          <ObjectChildTreePanel
            v-if="row.hasChildren && isHovering(group, row)"
            class="nested-panel"
            :root="{
              nodeId: group.nodeId,
              nodeName: group.title,
              attrName: row.displayName,
              attrAlias: row.type,
            }"
            :children="row.children"
            :root-path="row.rootPath"
            @hovering="onNestedHovering"
            @select="selectSelector"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAvailableVariables } from '../../model/useAvailableVariables.js'
import {
  getRootSelectorPath,
  hasNestedChildren,
  buildNestedValueSelector,
  getTreeRootLabel,
} from '../../model/objectChildTree.js'
import { formatValueSelector } from '../../model/variableOutputs.js'
import ObjectChildTreePanel from './ObjectChildTreePanel.vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  nodeId: { type: String, required: true },
  placeholder: { type: String, default: '选择变量...' },
  disabled: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
  clearable: { type: Boolean, default: true },
  hideFileVars: { type: Boolean, default: false },
  filterVar: { type: Function, default: null },
})

const emit = defineEmits(['update:modelValue', 'change'])

const { availableVarGroups } = useAvailableVariables(
  () => props.nodeId,
  {
    hideFileVars: computed(() => props.hideFileVars),
    filterVar: computed(() => props.filterVar),
  },
)

const rootRef = ref(null)
const open = ref(false)
const hoverKey = ref('')
const nestedHovering = ref(false)
let leaveTimer = null

const pickerGroups = computed(() => (
  availableVarGroups.value.map(group => ({
    nodeId: group.nodeId,
    title: group.title,
    rows: (group.vars || [])
      .filter(variable => (
        (!props.hideFileVars || (variable.type !== 'file' && variable.type !== 'arrayFile'))
        && (!props.filterVar || props.filterVar(variable))
      ))
      .map((variable) => {
      const rootPath = getRootSelectorPath(variable)
      return {
        variable: variable.variable,
        type: variable.type,
        des: variable.des,
        children: variable.children,
        displayName: getTreeRootLabel(variable),
        hasChildren: hasNestedChildren(variable),
        rootPath,
        selector: buildNestedValueSelector(group.nodeId, rootPath, []),
      }
    }),
  })).filter(group => group.rows.length > 0)
))

const displayText = computed(() => formatValueSelector(props.modelValue))

function optionKey(group, row) {
  return `${group.nodeId}::${row.variable}`
}

function isHovering(group, row) {
  return hoverKey.value === optionKey(group, row)
}

function isSelected(selector) {
  return JSON.stringify(selector || []) === JSON.stringify(props.modelValue || [])
}

function toggleOpen() {
  if (props.disabled || props.readOnly)
    return
  open.value = !open.value
}

function selectSelector(selector) {
  emit('update:modelValue', selector)
  emit('change', selector)
  open.value = false
  hoverKey.value = ''
  nestedHovering.value = false
}

function onClear() {
  selectSelector([])
}

function onEnterOption(group, row) {
  clearTimeout(leaveTimer)
  hoverKey.value = optionKey(group, row)
}

function onLeaveOption() {
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

function onDocPointerDown(event) {
  if (!open.value)
    return
  if (rootRef.value && !rootRef.value.contains(event.target))
    open.value = false
}

onMounted(() => document.addEventListener('mousedown', onDocPointerDown))
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocPointerDown)
  clearTimeout(leaveTimer)
})

defineExpose({ displayText })
</script>

<style scoped>
.var-ref-picker {
  position: relative;
  width: 100%;
}
.trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 32px;
  padding: 4px 10px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  text-align: left;
}
.trigger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background: #f9fafb;
}
.trigger-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: #344054;
  font-family: ui-monospace, monospace;
}
.trigger-text.placeholder {
  color: #98a2b3;
  font-family: inherit;
}
.clear,
.caret {
  color: #98a2b3;
  font-size: 12px;
}
.dropdown {
  position: absolute;
  z-index: 40;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  max-height: 280px;
  overflow: auto;
  padding: 6px;
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.12);
}
.group + .group {
  margin-top: 6px;
}
.group-title {
  padding: 4px 8px;
  font-size: 11px;
  color: #667085;
  font-weight: 600;
}
.option-wrap {
  position: relative;
}
.option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.option:hover,
.option.hovering,
.option.active {
  background: #f2f4f7;
}
.var-name {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: #155eef;
}
.var-type {
  font-size: 10px;
  color: #98a2b3;
  background: #f2f4f7;
  padding: 1px 5px;
  border-radius: 4px;
}
.chevron {
  margin-left: auto;
  color: #98a2b3;
}
.nested-panel {
  position: absolute;
  top: 0;
  left: calc(100% + 4px);
  z-index: 41;
}
.empty-hint {
  font-size: 12px;
  color: #98a2b3;
  padding: 8px;
}
</style>
