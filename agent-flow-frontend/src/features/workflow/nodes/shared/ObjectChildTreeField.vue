<template>
  <div class="tree-field">
    <button
      type="button"
      class="field-row"
      :class="{ deep: depth > maxDepth }"
      :disabled="depth > maxDepth"
      @mousedown.prevent="emit('select', [...path, name])"
    >
      <span class="indent" :style="{ width: `${(depth - 1) * 12}px` }" />
      <span v-if="depth > maxDepth" class="more">⋯</span>
      <span v-else class="name">{{ name }}</span>
      <span v-if="depth <= maxDepth" class="type">{{ type }}</span>
    </button>
    <template v-if="depth <= maxDepth && childFields.length">
      <ObjectChildTreeField
        v-for="child in childFields"
        :key="child.name"
        :name="child.name"
        :type="child.type"
        :children="child.children"
        :path="[...path, name]"
        :depth="depth + 1"
        @select="emit('select', $event)"
      />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { listTreeFields, OBJECT_TREE_MAX_DEPTH } from '../../model/objectChildTree.js'

const props = defineProps({
  name: { type: String, required: true },
  type: { type: String, default: 'string' },
  children: { type: [Array, Object], default: () => [] },
  path: { type: Array, default: () => [] },
  depth: { type: Number, default: 1 },
})

const emit = defineEmits(['select'])
const maxDepth = OBJECT_TREE_MAX_DEPTH
const childFields = computed(() => listTreeFields(props.children))
</script>

<style scoped>
.field-row {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 6px;
  padding: 2px 6px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.field-row:hover:not(:disabled) {
  background: #f2f4f7;
}
.field-row:disabled {
  cursor: default;
}
.indent {
  flex-shrink: 0;
}
.name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 500;
  color: #344054;
  font-family: ui-monospace, monospace;
}
.type {
  flex-shrink: 0;
  font-size: 11px;
  color: #98a2b3;
}
.more {
  color: #98a2b3;
  font-size: 12px;
}
</style>
