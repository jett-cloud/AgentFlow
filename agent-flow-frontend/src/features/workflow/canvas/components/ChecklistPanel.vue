<template>
  <aside v-if="open" class="checklist-panel" aria-label="工作流检查清单">
    <header>
      <div>
        <h2>检查清单{{ groups.length ? ` (${groups.length})` : '' }}</h2>
        <p>{{ summary }}</p>
      </div>
      <button type="button" aria-label="关闭检查清单" @click="$emit('close')">×</button>
    </header>
    <ul v-if="groups.length" class="checklist-list">
      <li
        v-for="group in groups"
        :key="group.id"
        :data-level="group.level"
        :class="{ clickable: group.canNavigate }"
        @click="onGroupClick(group)"
      >
        <div class="group-head">
          <span class="level-dot" aria-hidden="true"></span>
          <span class="group-title">{{ group.title }}</span>
          <span class="group-count">{{ group.messages.length }} 个问题</span>
          <button
            v-if="group.canNavigate"
            type="button"
            class="goto"
            @click.stop="onGroupClick(group)"
          >
            定位
          </button>
        </div>
        <ul class="msg-list">
          <li v-for="(msg, idx) in group.messages" :key="idx">{{ msg }}</li>
        </ul>
      </li>
    </ul>
    <div v-else class="checklist-empty">当前图结构通过基础检查，可以保存或发布。</div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { groupChecklistIssues } from '../../model/checklist.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  issues: { type: Array, default: () => [] },
  groupedIssues: { type: Array, default: null },
  issueCount: { type: Number, default: 0 },
})

const emit = defineEmits(['close', 'goto-node'])

const groups = computed(() => (
  Array.isArray(props.groupedIssues)
    ? props.groupedIssues
    : groupChecklistIssues(props.issues)
))
const summary = computed(() => {
  if (!groups.value.length)
    return '暂无问题'
  const count = props.issueCount || props.issues.length
  return `${groups.value.length} 个节点，共 ${count} 个问题`
})

function onGroupClick(group) {
  if (!group?.canNavigate || !group.id) return
  emit('goto-node', group.id)
}
</script>

<style scoped>
.checklist-panel {
  position: absolute;
  top: 60px;
  right: 12px;
  z-index: 70;
  display: flex;
  flex-direction: column;
  width: 360px;
  max-height: calc(100% - 76px);
  overflow: hidden;
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.08);
}
header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid #eaecf0;
}
h2, p { margin: 0; }
h2 { font-size: 14px; color: #101828; }
p { margin-top: 2px; font-size: 11px; color: #667085; }
header button {
  border: 0;
  border-radius: 6px;
  background: transparent;
  padding: 4px 8px;
  cursor: pointer;
}
header button:hover { background: #f2f4f7; }
.checklist-list {
  flex: 1 1 auto;
  min-height: 0;
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-color: #d0d5dd transparent;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
}
.checklist-list::-webkit-scrollbar {
  width: 8px;
}
.checklist-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: #d0d5dd;
}
.checklist-list > li {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-radius: 8px;
  margin-bottom: 6px;
  background: #f9fafb;
  border: 1px solid transparent;
}
.checklist-list > li.clickable {
  cursor: pointer;
}
.checklist-list > li.clickable:hover {
  border-color: #d0d5dd;
  background: #f2f4f7;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.group-title {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: #101828;
}
.level-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: #f79009;
}
.group-count {
  flex: none;
  border-radius: 999px;
  background: #f2f4f7;
  padding: 2px 7px;
  color: #667085;
  font-size: 10px;
  font-weight: 600;
}
.goto {
  border: 0;
  border-radius: 6px;
  background: #eff8ff;
  color: #175cd3;
  font-size: 11px;
  padding: 2px 8px;
  cursor: pointer;
}
.msg-list {
  list-style: none;
  margin: 0;
  padding: 0 0 0 2px;
}
.msg-list li {
  font-size: 12px;
  color: #344054;
  line-height: 1.4;
}
.checklist-list > li[data-level='error'] .level-dot { background: #f04438; }
.checklist-list > li[data-level='warning'] .level-dot { background: #f79009; }
.checklist-empty {
  padding: 24px 14px;
  text-align: center;
  color: #667085;
  font-size: 12px;
}
</style>
