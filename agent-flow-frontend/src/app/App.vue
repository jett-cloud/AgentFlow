<template>
  <el-container v-if="route.path !== '/login'" class="app-layout" :class="{ 'is-editor-mode': isEditorMode }">
    <header v-if="!isEditorMode" class="app-header">
      <button
        type="button"
        class="sidebar-trigger"
        aria-label="打开导航"
        :aria-expanded="sidebarOpen"
        @click="sidebarOpen = true"
      >
        <span class="sidebar-trigger-mark" />
      </button>
      <span class="app-header-title">{{ activeNavigationLabel }}</span>
    </header>

    <Transition name="sidebar-fade">
      <div v-if="sidebarOpen && !isEditorMode" class="sidebar-layer" @click.self="sidebarOpen = false">
        <aside class="app-sidebar" aria-label="工作区导航">
          <div class="sidebar-profile">
            <UserMenu
              :username="userInfo.username"
              :role="roleText"
              :avatar-text="avatarText"
              @logout="handleLogout"
            />
            <button type="button" class="sidebar-close" aria-label="关闭导航" @click="sidebarOpen = false">×</button>
          </div>
          <TopNavigation :active-id="activeNavigation" />
        </aside>
      </div>
    </Transition>

    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>

  <router-view v-else />
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import TopNavigation from './components/TopNavigation.vue'
import UserMenu from './components/UserMenu.vue'
import { resolveActiveNavigation } from './navigation.js'
import { getDifyProfile, logoutFromDify } from '../shared/auth/difyAuth.js'

const route = useRoute()
const router = useRouter()
const isEditorMode = computed(() => route.path === '/' && !!String(route.query.appId || '').trim())
const activeNavigation = computed(() => resolveActiveNavigation(route.path))
const activeNavigationLabel = computed(() => ({
  copilot: '工作流编排',
  integrations: '模型与工具',
  knowledge: '知识库',
}[activeNavigation.value] || '工作台'))
const sidebarOpen = ref(false)

const userInfo = ref({
  username: 'Dify 用户',
  roles: ['User'],
})

async function fetchUserInfo() {
  if (route.path === '/login')
    return

  try {
    const profile = await getDifyProfile()
    userInfo.value.username = profile.name || profile.email || 'Dify 用户'
    userInfo.value.roles = ['User']
  }
  catch (error) {
    console.error('Failed to fetch user info:', error)
  }
}

onMounted(fetchUserInfo)

watch(() => route.path, (newPath) => {
  sidebarOpen.value = false
  if (newPath !== '/login')
    fetchUserInfo()
})

const avatarText = computed(() => {
  const name = userInfo.value.username
  return name ? name.substring(0, 2).toUpperCase() : 'AD'
})

const roleText = computed(() => {
  const roles = userInfo.value.roles
  if (!roles?.length)
    return 'User'

  const primaryRole = roles[0]
  if (primaryRole === 'ADMIN')
    return 'Administrator'
  if (primaryRole === 'USER')
    return 'User'
  return primaryRole.charAt(0).toUpperCase() + primaryRole.slice(1).toLowerCase()
})

function handleLogout() {
  ElMessageBox.confirm('确定要退出当前账号并返回登录吗？', '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
    customClass: 'agentflow-confirm-dialog',
  }).then(async () => {
    try {
      await logoutFromDify()
    }
    catch (error) {
      console.error('Logout API failed:', error)
    }

    ElMessage({
      message: '已成功退出登录',
      type: 'success',
      duration: 1500,
    })
    router.push('/login')
  }).catch(() => {})
}
</script>

<style>
:root {
  --af-page: #f6f7f9;
  --af-surface: #ffffff;
  --af-surface-subtle: #f0f1f3;
  --af-text-primary: #25272c;
  --af-text-secondary: #505762;
  --af-text-muted: #737b87;
  --af-border: #dfe2e7;
  --af-border-strong: #c8cdd4;
  --af-brand: #5368a9;
  --af-brand-strong: #43558d;
  --af-brand-soft: #eef0f8;
  --af-brand-border: #cbd2ea;
  --af-focus-ring: rgba(83, 104, 169, 0.2);
  --af-radius-sm: 7px;
  --af-radius-md: 10px;
  --af-radius-lg: 12px;
  --af-shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.04);
  --af-transition: 160ms ease;
  --color-primary: var(--af-brand);
  --color-primary-hover: var(--af-brand-strong);
  --color-primary-light: var(--af-brand-soft);
  --color-primary-light-hover: #e2e6f3;
  --color-success: #12b76a;
  --color-warning: #f79009;
  --color-danger: #f04438;
  --color-info: #667085;
  --bg-primary: var(--af-page);
  --bg-secondary: var(--af-surface);
  --bg-tertiary: var(--af-surface-subtle);
  --bg-quaternary: #e2e8f0;
  --text-primary: var(--af-text-primary);
  --text-secondary: var(--af-text-secondary);
  --text-muted: var(--af-text-muted);
  --text-inverse: #ffffff;
  --border-color: var(--af-border);
  --font-sans: 'Noto Sans SC', 'Microsoft YaHei UI', 'PingFang SC', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;

  --el-color-primary: var(--color-primary) !important;
  --el-font-family: var(--font-sans) !important;
  --el-font-weight-primary: 550 !important;
  --el-color-primary-light-3: #7d8dbd !important;
  --el-color-primary-light-5: #9ea9ca !important;
  --el-color-primary-light-7: #c0c7dc !important;
  --el-color-primary-light-8: #d3d8e7 !important;
  --el-color-primary-light-9: var(--af-brand-soft) !important;
  --el-color-primary-dark-2: var(--color-primary-hover) !important;
  --el-text-color-primary: var(--text-primary) !important;
  --el-text-color-regular: var(--text-secondary) !important;
  --el-text-color-secondary: var(--text-muted) !important;
  --el-text-color-placeholder: #94a3b8 !important;
  --el-border-color: var(--border-color) !important;
  --el-border-color-light: #f2f4f7 !important;
  --el-border-color-lighter: #f8f9fa !important;
  --el-bg-color: var(--bg-primary) !important;
  --el-bg-color-page: var(--bg-primary) !important;
  --el-bg-color-overlay: var(--bg-secondary) !important;
}

html,
body,
#app {
  width: 100%;
  height: 100%;
  padding: 0;
  margin: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-family: var(--font-sans);
  background-color: var(--bg-primary);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

button,
input,
textarea,
select,
.el-button,
.el-input,
.el-select,
.el-dropdown,
.el-dialog {
  font-family: var(--font-sans) !important;
}

button,
.el-button,
.el-dropdown-menu__item {
  font-weight: 550;
}

.vue-flow__handle {
  width: 8px !important;
  height: 8px !important;
  background: var(--bg-secondary) !important;
  border: 2px solid #94a3b8 !important;
  border-radius: 50% !important;
  transition: all 0.2s ease !important;
}

.vue-flow__handle:hover {
  background: var(--color-primary) !important;
  border-color: var(--color-primary) !important;
  box-shadow: 0 0 0 4px rgba(21, 94, 239, 0.2) !important;
  transform: scale(1.3) !important;
}

.agentflow-confirm-dialog {
  padding: 24px !important;
  border: 1px solid #eaecf0 !important;
  border-radius: 12px !important;
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.08) !important;
}

.agentflow-confirm-dialog .el-message-box__title {
  font-size: 16px !important;
  font-weight: 700 !important;
}

.agentflow-confirm-dialog .el-message-box__btns .el-button {
  padding: 8px 16px !important;
  border-radius: 6px !important;
}

.app-layout {
  display: flex;
  width: 100vw;
  height: 100vh;
  flex-direction: column;
  overflow: hidden;
}

.app-header {
  position: relative;
  z-index: 40;
  display: flex;
  height: 56px;
  min-height: 56px;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--af-border);
}
.sidebar-trigger { display: grid; width: 32px; height: 32px; padding: 0; place-items: center; border: 1px solid transparent; border-radius: 8px; background: transparent; cursor: pointer; }
.sidebar-trigger:hover { border-color: var(--af-border); background: var(--af-surface-subtle); }
.sidebar-trigger:focus-visible, .sidebar-close:focus-visible { outline: 3px solid var(--af-focus-ring); outline-offset: 1px; }
.sidebar-trigger-mark { position: relative; width: 18px; height: 18px; border: 1.7px solid var(--af-text-secondary); border-radius: 5px; }
.sidebar-trigger-mark::before { position: absolute; top: 3px; bottom: 3px; left: 4px; width: 1.7px; border-radius: 2px; background: var(--af-text-secondary); content: ''; }
.app-header-title { color: var(--af-text-primary); font-size: 14px; font-weight: 600; }
.sidebar-layer { position: fixed; z-index: 1000; inset: 0; background: rgb(24 26 30 / 18%); }
.app-sidebar { display: flex; width: 284px; height: 100%; padding: 16px 12px; flex-direction: column; gap: 18px; border-right: 1px solid var(--af-border); background: var(--af-surface); box-shadow: 12px 0 34px rgb(24 30 42 / 12%); }
.sidebar-profile { display: flex; align-items: center; justify-content: space-between; padding: 0 4px; }
.sidebar-close { width: 32px; height: 32px; border: 0; border-radius: 8px; background: transparent; color: var(--af-text-muted); font-size: 22px; cursor: pointer; }
.sidebar-close:hover { background: var(--af-surface-subtle); color: var(--af-text-primary); }
.sidebar-fade-enter-active, .sidebar-fade-leave-active { transition: opacity 180ms ease; }
.sidebar-fade-enter-active .app-sidebar, .sidebar-fade-leave-active .app-sidebar { transition: transform 180ms cubic-bezier(.2,.8,.2,1); }
.sidebar-fade-enter-from, .sidebar-fade-leave-to { opacity: 0; }
.sidebar-fade-enter-from .app-sidebar, .sidebar-fade-leave-to .app-sidebar { transform: translateX(-16px); }

.app-main {
  width: 100%;
  min-height: 0;
  flex: 1;
  padding: 0 !important;
  margin: 0 !important;
  overflow: hidden;
  background-color: var(--bg-primary);
}

.app-layout.is-editor-mode .app-main {
  max-width: none !important;
  padding: 0 !important;
  margin: 0 !important;
}

@media (max-width: 600px) {
  .app-header {
    height: 58px;
    min-height: 58px;
    padding: 0 10px;
  }
  .app-sidebar { width: min(284px, calc(100vw - 32px)); }
}
</style>
