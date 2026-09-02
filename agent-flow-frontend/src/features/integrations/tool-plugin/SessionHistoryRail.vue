<template>
  <aside class="session-rail" :class="{ collapsed }">
    <header class="rail-header">
      <button
        type="button"
        class="icon-btn"
        :title="collapsed ? '展开侧栏' : '折叠侧栏'"
        @click="toggleCollapsed"
      >
        <svg v-if="collapsed" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path
            fill="currentColor"
            d="M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h16v2H4v-2z"
          />
        </svg>
        <svg v-else viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path
            fill="currentColor"
            d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"
          />
        </svg>
      </button>
      <span v-if="!collapsed" class="rail-brand">对话</span>
      <button
        v-if="!collapsed"
        type="button"
        class="icon-btn"
        title="折叠侧栏"
        @click="toggleCollapsed"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path
            fill="currentColor"
            d="M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z"
          />
        </svg>
      </button>
    </header>

    <div class="rail-actions">
      <button
        type="button"
        class="new-chat-btn"
        :disabled="disabled"
        :title="collapsed ? '空白新建' : undefined"
        @click="$emit('new')"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path
            fill="currentColor"
            d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"
          />
        </svg>
        <span v-if="!collapsed">空白新建</span>
      </button>
      <button
        v-if="!collapsed"
        type="button"
        class="fork-chat-btn"
        :disabled="disabled"
        @click="$emit('fork-pick')"
      >
        从已有插件…
      </button>
      <button
        v-if="!collapsed"
        type="button"
        class="ghost-btn"
        :class="{ on: showHidden }"
        :disabled="disabled"
        @click="$emit('update:showHidden', !showHidden)"
      >
        {{ showHidden ? '隐藏已归档' : '显示已隐藏' }}
      </button>
    </div>

    <div v-if="!collapsed" class="rail-body">
      <div class="section-label">历史</div>

      <p v-if="!sessions.length" class="session-empty">
        开始对话后，历史记录会出现在这里。
      </p>

      <div v-for="group in groupedSessions" :key="group.label" class="session-group">
        <div class="group-label">{{ group.label }}</div>
        <div
          v-for="item in group.items"
          :key="item.id"
          class="session-item"
          :class="{ active: item.id === activeId, hidden: item.is_hidden }"
        >
          <button
            type="button"
            class="session-main"
            :disabled="disabled"
            :title="item.display_name || item.plugin_name"
            @click="$emit('open', item.id)"
          >
            <span class="session-title">{{ item.display_name || item.plugin_name }}</span>
          </button>
          <div class="session-menu">
            <button
              type="button"
              class="menu-trigger"
              title="更多"
              :disabled="disabled"
              @click.stop="toggleMenu(item.id)"
            >
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M6 10c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm6 0c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm6 0c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"
                />
              </svg>
            </button>
            <div v-if="openMenuId === item.id" class="menu-pop" @click.stop>
              <button
                v-if="item.is_hidden"
                type="button"
                @click="emitAction('unhide', item.id)"
              >
                取消隐藏
              </button>
              <button
                v-else
                type="button"
                @click="emitAction('hide', item.id)"
              >
                隐藏
              </button>
              <button type="button" class="danger" @click="emitAction('delete', item.id)">
                删除
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  showHidden: { type: Boolean, default: false },
  collapsed: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['new', 'fork-pick', 'open', 'hide', 'unhide', 'delete', 'update:showHidden', 'update:collapsed'])

const openMenuId = ref('')

function toggleCollapsed() {
  emit('update:collapsed', !props.collapsed)
}

function toggleMenu(id) {
  openMenuId.value = openMenuId.value === id ? '' : id
}

function emitAction(type, id) {
  openMenuId.value = ''
  emit(type, id)
}

function closeMenu() {
  openMenuId.value = ''
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

function groupKey(iso) {
  if (!iso)
    return 'older'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime()))
    return 'older'
  const now = new Date()
  const today = startOfDay(now)
  const target = startOfDay(date)
  const diffDays = Math.round((today - target) / 86400000)
  if (diffDays <= 0)
    return 'today'
  if (diffDays === 1)
    return 'yesterday'
  if (diffDays < 7)
    return 'week'
  if (diffDays < 30)
    return 'month'
  return 'older'
}

const GROUP_ORDER = [
  { key: 'today', label: '今天' },
  { key: 'yesterday', label: '昨天' },
  { key: 'week', label: '近 7 天' },
  { key: 'month', label: '近 30 天' },
  { key: 'older', label: '更早' },
]

const groupedSessions = computed(() => {
  const buckets = {
    today: [],
    yesterday: [],
    week: [],
    month: [],
    older: [],
  }
  for (const item of props.sessions)
    buckets[groupKey(item.updated_at)].push(item)
  return GROUP_ORDER
    .filter(group => buckets[group.key].length)
    .map(group => ({ label: group.label, items: buckets[group.key] }))
})

watch(() => props.sessions, closeMenu)
watch(() => props.collapsed, closeMenu)

onMounted(() => {
  document.addEventListener('click', closeMenu)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', closeMenu)
})
</script>

<style scoped>
.session-rail {
  --ink: #101828;
  --body: #344054;
  --muted: #667085;
  --muted-soft: #98a2b3;
  --hairline: #eaecf0;
  --hairline-strong: #d0d5dd;
  --canvas: #f9fafb;
  --surface: #ffffff;
  --surface-strong: #f2f4f7;
  --primary: #5368a9;
  --primary-active: #43558d;
  --error: #d92d20;
  --hover: rgb(16 24 40 / 4%);
  --font: system-ui, "Helvetica Neue", Helvetica, Arial, sans-serif;

  width: 260px;
  flex-shrink: 0;
  border: 1px solid var(--hairline);
  border-radius: 12px;
  background: var(--canvas);
  color: var(--ink);
  font-family: var(--font);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  transition: width 0.15s ease;
}
.session-rail.collapsed {
  width: 52px;
}

.rail-header {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 10px 4px;
}
.collapsed .rail-header {
  justify-content: center;
}
.rail-brand {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}
.icon-btn {
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}
.icon-btn:hover:not(:disabled) {
  color: var(--ink);
  background: var(--hover);
}
.icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.rail-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 10px 8px;
}
.new-chat-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 12px;
  border: 0;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease;
}
.collapsed .new-chat-btn {
  justify-content: center;
  padding: 0;
  width: 32px;
  height: 32px;
  margin: 0 auto;
}
.new-chat-btn:hover:not(:disabled) {
  background: var(--primary-active);
}
.new-chat-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.fork-chat-btn {
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--hairline-strong);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}
.fork-chat-btn:hover:not(:disabled) {
  background: var(--hover);
}
.fork-chat-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ghost-btn {
  border: 0;
  background: transparent;
  color: var(--muted-soft);
  font-size: 12px;
  text-align: left;
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}
.ghost-btn:hover:not(:disabled),
.ghost-btn.on {
  color: var(--ink);
  background: var(--hover);
}

.rail-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 4px 8px 12px;
}
.section-label,
.group-label {
  padding: 8px 8px 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.88px;
  text-transform: uppercase;
  color: var(--muted);
}
.session-group + .session-group {
  margin-top: 10px;
}
.session-empty {
  margin: 8px;
  font-size: 13px;
  line-height: 1.4;
  color: var(--muted);
}

.session-item {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 32px;
  border-radius: 8px;
}
.session-main {
  flex: 1;
  min-width: 0;
  height: 32px;
  border: 0;
  background: transparent;
  text-align: left;
  padding: 0 8px;
  cursor: pointer;
  color: var(--body);
  font-size: 13px;
  border-radius: 8px;
  transition: color 0.15s ease, background 0.15s ease;
}
.session-main:hover:not(:disabled) {
  color: var(--ink);
  background: var(--hover);
}
.session-item.active .session-main {
  color: var(--ink);
  font-weight: 600;
  background: var(--surface);
  border: 1px solid var(--hairline);
}
.session-item.hidden .session-main {
  opacity: 0.7;
}
.session-title {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-menu {
  position: relative;
  flex-shrink: 0;
  padding-right: 2px;
}
.menu-trigger {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.session-item:hover .menu-trigger,
.session-item.active .menu-trigger,
.session-item:focus-within .menu-trigger {
  opacity: 1;
}
.menu-trigger:hover:not(:disabled) {
  color: var(--ink);
  background: var(--hover);
}
.menu-pop {
  position: absolute;
  right: 0;
  top: 30px;
  z-index: 8;
  min-width: 120px;
  padding: 4px;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  background: var(--surface);
  display: flex;
  flex-direction: column;
}
.menu-pop button {
  border: 0;
  background: transparent;
  text-align: left;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--ink);
}
.menu-pop button:hover {
  background: var(--canvas);
}
.menu-pop .danger {
  color: var(--error);
}
</style>
