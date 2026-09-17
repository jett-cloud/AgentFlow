<template>
  <div class="list-panel">
    <PanelHeader
      block-type="list-operator"
      :title="nodeTitle"
      :description="nodeData.desc"
      :legacy-description="nodeData.description"
      placeholder="列表操作"
      :read-only="readOnly"
      @update:title="onTitleChange"
      @update:description="onDescriptionChange"
      @close="$emit('close')"
    />

    <div class="panel-body">
      <PanelSection label="输入变量" required>
        <VarReferencePicker
          v-model="variable"
          :node-id="nodeId"
          :filter-var="arrayTypeFilter"
          placeholder="选择数组变量"
          :read-only="readOnly"
        />
        <span class="field-tip">仅显示当前节点可访问的数组变量。</span>
      </PanelSection>

      <el-alert
        v-if="legacyFilterCondition"
        type="warning"
        :closable="false"
        show-icon
        title="旧过滤表达式无法安全自动转换"
      >
        <template #default>
          <code>{{ legacyFilterCondition }}</code>
          <div class="legacy-tip">请在下方重新配置结构化过滤条件，保存后旧表达式会被移除。</div>
        </template>
      </el-alert>

      <PanelSection label="过滤条件" border-top>
        <template #extra>
          <el-switch v-model="filterEnabled" size="small" :disabled="readOnly || !variable.length" />
        </template>
        <div v-if="filterEnabled" class="condition-grid">
          <el-select
            v-if="hasFileSubVariables"
            v-model="filterKey"
            size="small"
            :disabled="readOnly"
            aria-label="文件字段"
          >
            <el-option v-for="key in FILE_FIELDS" :key="key" :label="key" :value="key" />
          </el-select>
          <el-select v-model="filterOperator" size="small" :disabled="readOnly" aria-label="比较操作符">
            <el-option v-for="operator in filterOperators" :key="operator" :label="operator" :value="operator" />
          </el-select>
          <el-select
            v-if="filterRequiresValue && itemType === 'boolean'"
            v-model="filterValue"
            size="small"
            :disabled="readOnly"
            aria-label="布尔值"
          >
            <el-option label="true" :value="true" />
            <el-option label="false" :value="false" />
          </el-select>
          <el-input
            v-else-if="filterRequiresValue"
            v-model="filterValue"
            :type="itemType === 'number' ? 'number' : 'text'"
            size="small"
            placeholder="比较值"
            :disabled="readOnly"
          />
        </div>
      </PanelSection>

      <PanelSection label="提取元素" border-top>
        <template #extra>
          <el-switch v-model="extractEnabled" size="small" :disabled="readOnly || !variable.length" />
        </template>
        <el-input
          v-if="extractEnabled"
          v-model="extractSerial"
          size="small"
          placeholder="序号，例如 1"
          :disabled="readOnly"
        />
      </PanelSection>

      <PanelSection label="排序" border-top>
        <template #extra>
          <el-switch v-model="orderEnabled" size="small" :disabled="readOnly || !variable.length" />
        </template>
        <div v-if="orderEnabled" class="condition-grid">
          <el-select
            v-if="hasFileSubVariables"
            v-model="orderKey"
            size="small"
            :disabled="readOnly"
            aria-label="排序字段"
          >
            <el-option v-for="key in FILE_FIELDS" :key="key" :label="key" :value="key" />
          </el-select>
          <el-radio-group v-model="orderDirection" size="small" :disabled="readOnly">
            <el-radio-button value="asc">升序</el-radio-button>
            <el-radio-button value="desc">降序</el-radio-button>
          </el-radio-group>
        </div>
      </PanelSection>

      <PanelSection label="限制数量" border-top>
        <template #extra>
          <el-switch v-model="limitEnabled" size="small" :disabled="readOnly || !variable.length" />
        </template>
        <el-input-number
          v-if="limitEnabled"
          v-model="limitSize"
          :min="1"
          :max="20"
          size="small"
          :disabled="readOnly"
        />
      </PanelSection>

      <PanelSection label="输出变量" border-top>
        <OutputVarList :vars="outputVars" />
      </PanelSection>

      <NextStep :node-id="nodeId" :node-data="nodeData" :read-only="readOnly" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import PanelHeader from '../shared/PanelHeader.vue'
import PanelSection from '../shared/PanelSection.vue'
import VarReferencePicker from '../shared/VarReferencePicker.vue'
import OutputVarList from '../shared/OutputVarList.vue'
import NextStep from '../shared/NextStep.vue'
import { useListOperatorConfig } from './useListOperatorConfig.js'

const FILE_FIELDS = ['name', 'url', 'extension', 'mime_type', 'related_id', 'size']

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])

const {
  readOnly,
  variable,
  filterEnabled,
  filterKey,
  filterOperator,
  filterValue,
  filterOperators,
  filterRequiresValue,
  extractEnabled,
  extractSerial,
  orderEnabled,
  orderKey,
  orderDirection,
  limitEnabled,
  limitSize,
  legacyFilterCondition,
  hasFileSubVariables,
  itemType,
  arrayTypeFilter,
} = useListOperatorConfig(props, emit)

const nodeTitle = computed(() => props.nodeData?.title || '列表操作')
const outputVars = computed(() => [
  { variable: 'result', type: props.nodeData?.var_type || 'array', des: '处理后的列表' },
  { variable: 'first_record', type: itemType.value, des: '第一条记录' },
  { variable: 'last_record', type: itemType.value, des: '最后一条记录' },
])

function onTitleChange(title) {
  emit('update:nodeData', { ...props.nodeData, title })
}

function onDescriptionChange(desc) {
  const { description: _legacyDescription, ...nodeData } = props.nodeData
  emit('update:nodeData', { ...nodeData, desc })
}
</script>

<style scoped>
.list-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #fff;
  border-left: 1px solid #eaecf0;
}
.panel-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
  padding: 16px;
  overflow-y: auto;
}
.field-tip,
.legacy-tip {
  color: #98a2b3;
  font-size: 11px;
  line-height: 1.5;
}
.condition-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}
code {
  font-family: ui-monospace, monospace;
  font-size: 11px;
}
</style>
