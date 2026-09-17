<!--
  Nested object/file field tree (Dify PickerStructurePanel).
  Emits full value_selector arrays via @select.
-->
<template>
  <div
    class="object-child-tree"
    @mouseenter="emit('hovering', true)"
    @mouseleave="onLeave"
  >
    <div class="tree-header">
      <div class="tree-path">
        <template v-if="root.nodeName">
          <span class="muted truncate">{{ root.nodeName }}</span>
          <span class="muted">.</span>
        </template>
        <span class="attr">{{ root.attrName }}</span>
      </div>
      <span class="type">{{ root.attrAlias || 'object' }}</span>
    </div>
    <ObjectChildTreeField
      v-for="field in fields"
      :key="field.name"
      :name="field.name"
      :type="field.type"
      :children="field.children"
      :path="[...rootPath]"
      :depth="1"
      @select="onFieldSelect"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { listTreeFields, buildNestedValueSelector } from '../../model/objectChildTree.js'
import ObjectChildTreeField from './ObjectChildTreeField.vue'

const props = defineProps({
  /** { nodeId, nodeName?, attrName, attrAlias? } */
  root: { type: Object, required: true },
  /** Var.children | StructuredOutput */
  children: { type: [Array, Object], default: () => [] },
  /** Root selector path segments (already special-split). */
  rootPath: { type: Array, default: () => [] },
})

const emit = defineEmits(['select', 'hovering'])

const fields = computed(() => listTreeFields(props.children))

function onFieldSelect(childPath) {
  emit('select', buildNestedValueSelector(props.root.nodeId, props.rootPath, childPath))
}

function onLeave() {
  setTimeout(() => emit('hovering', false), 100)
}
</script>

<style scoped>
.object-child-tree {
  min-width: 220px;
  max-width: 320px;
  max-height: 280px;
  overflow: auto;
  padding: 6px;
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.12);
}
.tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 6px 8px;
  border-bottom: 1px solid #f2f4f7;
  margin-bottom: 4px;
}
.tree-path {
  display: flex;
  min-width: 0;
  font-size: 12px;
  font-weight: 500;
}
.muted {
  color: #98a2b3;
}
.attr {
  color: #344054;
}
.truncate {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.type {
  flex-shrink: 0;
  font-size: 11px;
  color: #98a2b3;
}
</style>
