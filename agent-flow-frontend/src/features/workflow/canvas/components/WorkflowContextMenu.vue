<template>
  <div
    v-if="visible"
    class="workflow-context-menu"
    :style="{ left: `${x}px`, top: `${y}px` }"
    role="menu"
    @click.stop
    @contextmenu.prevent
  >
    <template v-if="type === 'pane'">
      <button role="menuitem" type="button" @click="emitAction('add-node')">添加节点</button>
      <button role="menuitem" type="button" @click="emitAction('add-note')">添加便签</button>
      <button role="menuitem" type="button" :disabled="!canPaste" @click="emitAction('paste')">粘贴</button>
      <button role="menuitem" type="button" @click="emitAction('select-all')">全选</button>
    </template>

    <template v-else-if="type === 'node'">
      <button role="menuitem" type="button" @click="emitAction('run-node')">运行此节点</button>
      <span class="menu-separator"></span>
      <button role="menuitem" type="button" @click="emitAction('copy')">复制</button>
      <button role="menuitem" type="button" @click="emitAction('duplicate')">创建副本</button>
      <button role="menuitem" type="button" class="destructive" @click="emitAction('delete')">删除</button>
    </template>

    <template v-else-if="type === 'edge'">
      <button role="menuitem" type="button" @click="emitAction('insert-node')">插入节点</button>
      <button role="menuitem" type="button" class="destructive" @click="emitAction('delete')">删除连线</button>
    </template>

    <template v-else-if="type === 'selection'">
      <button role="menuitem" type="button" @click="emitAction('copy')">复制选中节点</button>
      <button role="menuitem" type="button" @click="emitAction('duplicate')">创建副本</button>
      <button role="menuitem" type="button" class="destructive" @click="emitAction('delete')">删除选中节点</button>
    </template>
  </div>
</template>

<script setup>
const props = defineProps({
  visible: { type: Boolean, default: false },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
  type: { type: String, default: 'pane' },
  canPaste: { type: Boolean, default: false },
})

const emit = defineEmits(['action'])

function emitAction(action) {
  if (action === 'paste' && !props.canPaste) return
  emit('action', action)
}
</script>

<style scoped>
.workflow-context-menu {
  position: absolute;
  z-index: 220;
  display: flex;
  width: 188px;
  flex-direction: column;
  gap: 2px;
  padding: 5px;
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
  border-radius: 10px;
  background: var(--components-panel-bg, #fff);
}

button {
  width: 100%;
  padding: 7px 9px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary, #354052);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

button:hover:not(:disabled),
button:focus-visible {
  outline: none;
  background: var(--components-actionbar-item-bg-hover, #f2f4f7);
  color: var(--text-primary, #101828);
}

button:focus-visible {
  box-shadow: 0 0 0 2px var(--state-accent-border, #0033ff) inset;
}

button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

button.destructive {
  color: var(--state-destructive-border, #f04438);
}

button.destructive:hover,
button.destructive:focus-visible {
  background: #fef3f2;
}

.menu-separator {
  height: 1px;
  margin: 3px 5px;
  background: var(--components-panel-border, rgba(16, 24, 40, 0.08));
}
</style>
