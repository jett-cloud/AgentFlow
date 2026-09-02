<!--
  Dify 风格块选择器：分 Tab（节点 / 工具 / 开始），工具 Tab 列出工作区目录。
  Start 页签仅在 AddBlock / 右键添加时由父组件开启（对齐 web AddBlock showStartTab）。
-->
<template>
  <div class="block-selector-host" :class="{ 'is-open': visible }">
    <div
      v-if="visible"
      class="block-selector"
      :style="menuStyle"
      @click.stop
    >
    <div class="bs-tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab.id"
        :class="{ active: activeTab === tab.id, disabled: tab.disabled }"
        :title="tab.disabled ? tab.disabledTip : undefined"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>
    <p v-if="activeTab === 'start' && startTabDisabled" class="bs-tip">
      {{ startDisabledTip }}
    </p>
    <div class="bs-search">
      <input
        ref="searchInput"
        v-model="keyword"
        class="bs-input"
        type="text"
        :placeholder="searchPlaceholder"
        :disabled="activeTab === 'start' && startTabDisabled"
      />
    </div>
    <div class="bs-list">
      <template v-if="activeTab === 'tools'">
        <section v-for="group in filteredToolGroups" :key="group.type" class="bs-group">
          <h3>{{ group.label }}</h3>
          <button
            v-for="tool in group.tools"
            :key="tool.provider_id + '::' + tool.tool_name"
            class="bs-item"
            type="button"
            @click="onPickTool(tool)"
          >
            <BlockIcon type="tool" :tool-icon="tool.icon || tool.icon_small" />
            <span class="bs-item-title">{{ tool.tool_label || tool.tool_name }}</span>
            <span class="bs-item-desc">{{ tool.provider_name }} · {{ tool.description || tool.provider_type }}</span>
          </button>
        </section>
        <div v-if="toolStore.loading" class="bs-empty">正在加载工具…</div>
        <div v-else-if="toolStore.loadError" class="bs-empty">{{ toolStore.loadError }}</div>
        <div v-else-if="!filteredToolGroups.length" class="bs-empty">
          暂无可用工具。请先到「工作区集成 → 工具授权」安装/授权。
        </div>
        <section class="bs-group">
          <h3>通用</h3>
          <button class="bs-item" type="button" @click="onPick('tool')">
            <BlockIcon type="tool" />
            <span class="bs-item-title">空白工具节点</span>
            <span class="bs-item-desc">稍后在右侧面板选择具体工具</span>
          </button>
          <button class="bs-item" type="button" @click="onPick('http-request')">
            <BlockIcon type="http-request" />
            <span class="bs-item-title">HTTP 请求</span>
            <span class="bs-item-desc">发起 HTTP 请求</span>
          </button>
        </section>
      </template>
      <template v-else-if="activeTab === 'start'">
        <section class="bs-group">
          <h3>开始</h3>
          <button
            v-for="item in filteredStartOptions"
            :key="item.type"
            class="bs-item"
            type="button"
            :disabled="startTabDisabled"
            @click="onPick(item.type)"
          >
            <BlockIcon :type="item.type" />
            <span class="bs-item-title">
              {{ item.title }}
              <em v-if="item.badge" class="bs-badge">{{ item.badge }}</em>
            </span>
            <span class="bs-item-desc">{{ item.desc }}</span>
          </button>
        </section>
        <div v-if="!filteredStartOptions.length" class="bs-empty">
          {{ startTabDisabled ? startDisabledTip : '无匹配开始节点' }}
        </div>
      </template>
      <template v-else>
        <section v-for="group in groupedBlocks" :key="group.name" class="bs-group">
          <h3>{{ group.name }}</h3>
          <button
            v-for="block in group.blocks"
            :key="block.type"
            class="bs-item"
            type="button"
            @click="onPick(block.type)"
          >
            <BlockIcon :type="block.type" />
            <span class="bs-item-title">{{ block.title }}</span>
            <span class="bs-item-desc">{{ block.desc }}</span>
          </button>
        </section>
        <div v-if="filtered.length === 0" class="bs-empty">无匹配节点</div>
      </template>
    </div>
  </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import BlockIcon from '../../nodes/base/BlockIcon.vue'
import {
  SELECTABLE_BLOCKS,
  CONTAINER_SELECTABLE_BLOCKS,
  START_BLOCK_OPTIONS,
  getNodeTitle,
  getBlockGroup,
  getSelectableBlocksForDirection,
} from '../../model/nodeMeta.js'
import { BlockEnum } from '../../model/constants.js'
import { buildEmptyToolParameters } from '../../model/toolParamInputs.js'
import { useToolStore } from '@/features/integrations/state/useToolStore.js'
import { groupSelectableTools } from '@/features/integrations/state/toolCatalog.js'
import { getBlockSelectorMenuStyle } from '../../model/blockSelectorPosition.js'
import { isEndAllowedInMode } from '../../nodes/end/endNode.js'
import { isAnswerAllowedInMode } from '../../nodes/er/answerNode.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
  /** default | container — 迭代/循环内使用精简列表 */
  mode: { type: String, default: 'default' },
  /** free | before | after | insert — filters structurally invalid choices */
  connectionDirection: { type: String, default: 'free' },
  /** 对齐官方 AddBlock showStartTab：仅空白添加入口开启 */
  showStartTab: { type: Boolean, default: false },
  /** 画布存在未配置的 start-placeholder 时禁用 Start 页签 */
  hasStartPlaceholder: { type: Boolean, default: false },
  /** 已有用户输入 Start 时隐藏「用户输入」行 */
  hasStartNode: { type: Boolean, default: false },
  /** End 只属于 Workflow，Answer 只属于 Chatflow。 */
  workflowMode: { type: String, default: 'workflow' },
  /** 当前循环容器未存在 loop-end 时由画布开启。 */
  allowLoopEnd: { type: Boolean, default: false },
})
const emit = defineEmits(['select'])

const keyword = ref('')
const searchInput = ref(null)
const activeTab = ref('blocks')
const toolStore = useToolStore()

const startDisabledTip = '请先在画布上配置未完成的开始节点'
const startTabDisabled = computed(() => props.hasStartPlaceholder)

const tabs = computed(() => {
  const list = [
    { id: 'blocks', label: '节点' },
    { id: 'tools', label: '工具' },
  ]
  if (props.showStartTab) {
    list.push({
      id: 'start',
      label: '开始',
      disabled: startTabDisabled.value,
      disabledTip: startDisabledTip,
    })
  }
  return list
})

const searchPlaceholder = computed(() => {
  if (activeTab.value === 'tools') return '搜索工具...'
  if (activeTab.value === 'start') return '搜索开始节点...'
  return '搜索节点...'
})

const BLOCK_DESC = {
  llm: '调用大语言模型',
  'knowledge-retrieval': '检索知识库片段',
  'question-classifier': '按意图分流',
  'if-else': '条件分支',
  code: '执行代码',
  'template-transform': '模板拼接',
  'http-request': '发起 HTTP 请求',
  tool: '调用工具',
  'parameter-extractor': '提取结构化参数',
  'variable-assigner': '聚合变量',
  assigner: '写入变量',
  'variable-aggregator': '聚合变量',
  'document-extractor': '提取文档内容',
  'list-operator': '列表过滤排序',
  agent: 'Agent V2（Soul 配置工具/知识库）',
  'knowledge-index': '写入知识库',
  'human-input': '人工审批',
  iteration: '遍历数组',
  loop: '循环执行',
  'loop-end': '立即退出当前循环',
  answer: '直接回复',
  end: '结束流程',
}

const TYPE_LABEL = {
  builtin: '工具插件',
  mcp: 'MCP 工具',
}

const sourceTypes = computed(() => {
  const types = props.mode === 'container'
    ? CONTAINER_SELECTABLE_BLOCKS
    : SELECTABLE_BLOCKS.filter(type => type !== 'tool')
  return getSelectableBlocksForDirection(types, props.connectionDirection)
    .filter(type => type !== BlockEnum.End || isEndAllowedInMode(props.workflowMode))
    .filter(type => type !== BlockEnum.Answer || isAnswerAllowedInMode(props.workflowMode))
    .filter(type => type !== BlockEnum.LoopEnd || props.allowLoopEnd)
})

const blocks = computed(() =>
  sourceTypes.value.map(type => ({
    type,
    title: getNodeTitle(type),
    desc: BLOCK_DESC[type] || type,
    group: getBlockGroup(type),
  })),
)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return blocks.value
  return blocks.value.filter(
    b => b.title.toLowerCase().includes(kw) || b.type.includes(kw) || b.desc.toLowerCase().includes(kw),
  )
})

const groupOrder = ['AI', '知识库', '逻辑', '转换', '工具', '输出', '入口']
const groupedBlocks = computed(() =>
  groupOrder
    .map(name => ({
      name,
      blocks: filtered.value.filter(block => block.group === name),
    }))
    .filter(group => group.blocks.length),
)

const startOptions = computed(() => {
  if (startTabDisabled.value) return []
  return START_BLOCK_OPTIONS.filter((item) => {
    if (item.type === BlockEnum.Start && props.hasStartNode)
      return false
    return true
  })
})

const filteredStartOptions = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return startOptions.value
  return startOptions.value.filter(
    item =>
      item.title.toLowerCase().includes(kw)
      || item.desc.toLowerCase().includes(kw)
      || item.type.includes(kw),
  )
})

const filteredToolGroups = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const tools = toolStore.allTools.filter((tool) => {
    if (!kw) return true
    const hay = `${tool.tool_label} ${tool.tool_name} ${tool.provider_name} ${tool.description}`.toLowerCase()
    return hay.includes(kw)
  })
  return groupSelectableTools(tools).map(group => ({ ...group, label: TYPE_LABEL[group.type] || group.label }))
})

const menuStyle = computed(() => getBlockSelectorMenuStyle({ x: props.x, y: props.y }))

watch(
  () => props.visible,
  (v) => {
    if (v) {
      keyword.value = ''
      activeTab.value = 'blocks'
      toolStore.fetchTools()
      nextTick(() => searchInput.value?.focus())
    }
  },
)

watch(
  () => props.showStartTab,
  (show) => {
    if (!show && activeTab.value === 'start')
      activeTab.value = 'blocks'
  },
)

function onPick(type) {
  if (activeTab.value === 'start' && startTabDisabled.value) return
  emit('select', { type })
}

function onPickTool(tool) {
  emit('select', {
    type: 'tool',
    data: {
      provider_id: tool.provider_id,
      provider_type: tool.provider_type,
      provider_name: tool.provider_name,
      provider_icon: tool.icon ?? tool.icon_small ?? null,
      tool_name: tool.tool_name,
      tool_label: tool.tool_label,
      tool_description: tool.description,
      is_team_authorization: tool.is_team_authorization,
      title: tool.tool_label || tool.tool_name,
      tool_parameters: buildEmptyToolParameters(tool.parameters || []),
      tool_configurations: {},
      tool_node_version: '2',
    },
  })
}
</script>

<style scoped>
.block-selector-host {
  display: contents;
}

.block-selector-host:not(.is-open) {
  pointer-events: none;
}

.block-selector {
  position: absolute;
  z-index: 110;
  width: 320px;
  max-height: 440px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 12px 32px rgb(16 24 40 / 14%);
}
.bs-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 8px 0;
}
.bs-tabs button {
  flex: 1;
  height: 32px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #667085;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.bs-tabs button.active {
  background: #eff4ff;
  color: #155eef;
}
.bs-tabs button.disabled,
.bs-tabs button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
.bs-tip {
  margin: 6px 12px 0;
  padding: 6px 8px;
  border-radius: 6px;
  background: #fffaeb;
  color: #b54708;
  font-size: 11px;
  line-height: 1.4;
}
.bs-search { padding: 8px; }
.bs-input {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border: 1px solid #eaecf0;
  border-radius: 8px;
  box-sizing: border-box;
  font-size: 13px;
}
.bs-input:disabled {
  background: #f9fafb;
  cursor: not-allowed;
}
.bs-list {
  flex: 1;
  overflow: auto;
  padding: 0 8px 10px;
}
.bs-group h3 {
  margin: 8px 4px 4px;
  color: #98a2b3;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.bs-item {
  width: 100%;
  display: grid;
  grid-template-columns: 28px 1fr;
  grid-template-rows: auto auto;
  column-gap: 8px;
  align-items: center;
  padding: 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.bs-item:hover:not(:disabled) { background: #f8fafc; }
.bs-item:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.bs-item :deep(.block-icon),
.bs-item > :first-child {
  grid-row: 1 / span 2;
}
.bs-item-title {
  color: #101828;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.bs-badge {
  padding: 1px 6px;
  border-radius: 999px;
  background: #eff4ff;
  color: #155eef;
  font-size: 10px;
  font-style: normal;
  font-weight: 600;
}
.bs-item-desc {
  color: #667085;
  font-size: 11px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bs-empty {
  padding: 16px 8px;
  color: #98a2b3;
  font-size: 12px;
  text-align: center;
}
</style>
