<template>
  <el-dropdown trigger="click" placement="bottom-end" @command="handleCommand">
    <button type="button" class="user-menu-trigger" aria-label="打开用户菜单">
      <span class="user-avatar">{{ avatarText.slice(0, 1).toUpperCase() }}</span>
      <span class="user-summary">
        <span class="user-name">{{ username }}</span>
        <span class="user-role">{{ role }}</span>
      </span>
      <svg class="chevron" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 0 1 1.06.02L10 11.168l3.71-3.938a.75.75 0 1 1 1.08 1.04l-4.25 4.5a.75.75 0 0 1-1.08 0l-4.25-4.5a.75.75 0 0 1 .02-1.06Z" clip-rule="evenodd" />
      </svg>
    </button>
    <template #dropdown>
      <el-dropdown-menu class="user-dropdown-menu">
        <div class="dropdown-profile">
          <span class="dropdown-name">{{ username }}</span>
          <span class="dropdown-role">{{ role }}</span>
        </div>
        <el-dropdown-item command="logout" divided>
          退出登录
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup>
defineProps({
  username: { type: String, required: true },
  role: { type: String, required: true },
  avatarText: { type: String, required: true },
})

const emit = defineEmits(['logout'])

function handleCommand(command) {
  if (command === 'logout')
    emit('logout')
}
</script>

<style scoped>
.user-menu-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: 210px;
  padding: 4px;
  color: var(--af-text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--af-radius-md);
  cursor: pointer;
  transition: border-color var(--af-transition), background-color var(--af-transition);
}

.user-menu-trigger:hover { background: var(--af-surface-subtle); }

.user-menu-trigger:focus-visible {
  outline: 3px solid var(--af-focus-ring);
  outline-offset: 2px;
}

.user-avatar {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  place-items: center;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  border: 2px solid #fff;
  border-radius: 50%;
  background: linear-gradient(145deg, #4285f4 0%, #255fca 100%);
  box-shadow: 0 0 0 1px rgb(60 64 67 / 20%);
}

.user-summary {
  display: flex;
  min-width: 0;
  flex-direction: row;
  align-items: flex-start;
}

.user-name,
.user-role {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-name { font-size: 13px; font-weight: 600; color: var(--af-text-primary); }
.user-role { display: none; }
.chevron { width: 16px; height: 16px; color: #98a2b3; }

.dropdown-profile {
  display: flex;
  min-width: 180px;
  padding: 10px 16px 8px;
  flex-direction: column;
}

.dropdown-name { color: #101828; font-size: 13px; font-weight: 600; }
.dropdown-role { margin-top: 2px; color: #667085; font-size: 11px; }

@media (max-width: 900px) {
  .user-menu-trigger { padding: 4px; }
}
</style>
