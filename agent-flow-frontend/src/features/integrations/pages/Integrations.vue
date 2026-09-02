<template>
  <div class="integrations-page">
    <header class="page-header">
      <div>
        <h1>工作区集成</h1>
        <p>管理已安装的模型与工具、凭证增删改。市场浏览与安装请进入独立市场页。</p>
      </div>
    </header>

    <div class="tabs" role="tablist">
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'models'"
        :class="{ active: activeTab === 'models' }"
        @click="setTab('models')"
      >
        模型提供商
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'tools'"
        :class="{ active: activeTab === 'tools' }"
        @click="setTab('tools')"
      >
        工具授权
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'mcp'"
        :class="{ active: activeTab === 'mcp' }"
        @click="setTab('mcp')"
      >
        MCP 工具
      </button>
    </div>

    <section class="tab-panel">
      <ModelProvidersPanel v-if="activeTab === 'models'" embedded />
      <ToolsAuthPanel v-else-if="activeTab === 'tools'" />
      <McpToolsPanel v-else />
    </section>
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ModelProvidersPanel from '../ui/ModelProvidersPanel.vue'
import ToolsAuthPanel from '../ui/ToolsAuthPanel.vue'
import McpToolsPanel from '../ui/McpToolsPanel.vue'

const route = useRoute()
const router = useRouter()

const activeTab = computed(() => {
  const tab = String(route.query.tab || 'models')
  return ['tools', 'mcp'].includes(tab) ? tab : 'models'
})

function setTab(tab) {
  router.replace({ path: '/integrations', query: { tab } })
}

watch(
  () => route.query.tab,
  (tab) => {
    if (!tab)
      router.replace({ path: '/integrations', query: { tab: 'models' } })
  },
  { immediate: true },
)
</script>

<style scoped>
.integrations-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 28px 32px 32px;
  box-sizing: border-box;
  background: var(--af-page);
  font-family: var(--font-sans);
}
.page-header {
  width: min(100%, 1440px);
  margin: 0 auto 22px;
}
.page-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.025em;
  color: var(--af-text-primary);
}
.page-header p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--af-text-muted);
}
.tabs {
  display: flex;
  gap: 4px;
  width: min(100%, 1440px);
  margin: 0 auto 12px;
  border-bottom: 1px solid var(--af-border);
}
.tabs button {
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  padding: 9px 12px;
  font-size: 13px;
  color: var(--af-text-muted);
  cursor: pointer;
}
.tabs button.active {
  border-color: var(--af-brand);
  color: var(--af-brand-strong);
  font-weight: 600;
}
.tab-panel {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  width: min(100%, 1440px);
  margin: 0 auto;
  border: 1px solid var(--af-border);
  border-radius: var(--af-radius-lg);
  background: var(--af-surface);
  box-shadow: var(--af-shadow-sm);
}
.integrations-page :deep(button),
.integrations-page :deep(input),
.integrations-page :deep(textarea),
.integrations-page :deep(select) {
  font-family: var(--font-sans);
}
.integrations-page :deep(button) {
  font-weight: 550;
  letter-spacing: .005em;
  transition: color var(--af-transition), background-color var(--af-transition), border-color var(--af-transition), box-shadow var(--af-transition), transform 90ms ease;
}
.integrations-page :deep(button:active:not(:disabled)) { transform: scale(.98); }
.integrations-page :deep(button:focus-visible),
.integrations-page :deep(input:focus-visible),
.integrations-page :deep(textarea:focus-visible),
.integrations-page :deep(select:focus-visible) {
  outline: 3px solid var(--af-focus-ring);
  outline-offset: 1px;
}
</style>
