<template>
  <aside v-if="open" class="checklist-panel" aria-label="工作流检查清单">
    <header>
      <div>
        <h2>检查清单{{ groups.length ? ` (${groups.length})` : '' }}</h2>
        <p>{{ groups.length ? '请修复以下问题后再发布' : '暂无问题' }}</p>
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
          <strong>{{ group.level === 'error' ? '错误' : '提示' }}</strong>
          <span class="group-title">{{ group.title }}</span>
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
})

const emit = defineEmits(['close', 'goto-node'])

const groups = computed(() => groupChecklistIssues(props.issues))

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
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow: auto;
  max-height: calc(100% - 56px);
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
.checklist-list > li[data-level='error'] .group-head strong { color: #b42318; }
.checklist-list > li[data-level='warning'] .group-head strong { color: #b54708; }
.checklist-empty {
  padding: 24px 14px;
  text-align: center;
  color: #667085;
  font-size: 12px;
}
</style>
