<!-- src/views/copilot/components/workflow/panel/document-extractor/DocExtractorPanel.vue -->
<template>
  <div class="doc-panel">
    <PanelHeader
      block-type="document-extractor"
      :title="nodeTitle"
      :description="nodeData.desc"
      :legacy-description="nodeData.description"
      placeholder="文档提取器"
      :read-only="readOnly"
      @update:title="onTitleChange"
      @update:description="onDescriptionChange"
      @close="$emit('close')"
    />

    <div class="panel-body">
      <PanelSection label="输入变量" required>
        <VarReferencePicker
          v-model="variableSelector"
          :node-id="nodeId"
          placeholder="选择 File / Array[File] 变量"
          :read-only="readOnly"
          :filter-var="fileInputFilter"
        />
        <div class="support-file-tips">
          <span>支持的文件类型：{{ supportTypesShowNames }}。</span>
          <a class="learn-more-link" :href="helpLink" target="_blank" rel="noopener noreferrer">了解更多</a>
        </div>
      </PanelSection>

      <PanelSection label="输出变量" border-top>
        <OutputVarList
          :vars="[{ variable: 'text', type: isArrayFile ? 'arrayString' : 'string', des: '提取的文本' }]"
        />
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
import { useDocExtractorConfig } from './useDocExtractorConfig.js'

const props = defineProps({
  nodeId: { type: String, required: true },
  nodeData: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:nodeData'])

const {
  readOnly,
  variableSelector,
  isArrayFile,
  fileInputFilter,
  supportTypesShowNames,
  helpLink,
} = useDocExtractorConfig(props, emit)

const nodeTitle = computed({
  get: () => props.nodeData?.title || '文档提取器',
  set: (val) => emit('update:nodeData', { ...props.nodeData, title: val }),
})

function onTitleChange(val) {
  emit('update:nodeData', { ...props.nodeData, title: val })
}

function onDescriptionChange(val) {
  const { description: _legacyDescription, ...nodeData } = props.nodeData
  emit('update:nodeData', { ...nodeData, desc: val })
}
</script>

<style scoped>
.doc-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #fff;
  border-left: 1px solid #eaecf0;
}
.panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.support-file-tips {
  font-size: 11px;
  color: #98a2b3;
  line-height: 1.5;
}
.learn-more-link {
  color: #155eef;
  text-decoration: none;
}
.learn-more-link:hover {
  text-decoration: underline;
}
</style>
