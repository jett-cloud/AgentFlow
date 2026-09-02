<template>
  <div class="pipeline-create">
    <header class="page-header">
      <button type="button" class="back" @click="$router.push('/datasets')">← 知识库</button>
      <h1>从知识流水线创建</h1>
      <p>选择模板、从空白创建，或导入 DSL。对齐 Dify `/datasets/create-from-pipeline`。</p>
    </header>

    <div class="actions">
      <el-button type="primary" :loading="creatingEmpty" @click="createEmpty">从空白创建</el-button>
      <el-button @click="importOpen = true">导入 DSL</el-button>
      <el-radio-group v-model="templateType" size="small" @change="loadTemplates">
        <el-radio-button value="built-in">内置模板</el-radio-button>
        <el-radio-button value="customized">自定义模板</el-radio-button>
      </el-radio-group>
    </div>

    <div v-loading="loading" class="grid">
      <article
        v-for="item in templates"
        :key="item.id || item.template_id"
        class="template-card"
      >
        <h3>{{ item.name || item.title || '未命名模板' }}</h3>
        <p>{{ item.description || item.brief || '暂无描述' }}</p>
        <el-button
          type="primary"
          size="small"
          :loading="applyingId === (item.id || item.template_id)"
          @click="applyTemplate(item)"
        >
          使用此模板
        </el-button>
      </article>
      <div v-if="!loading && !templates.length" class="empty">
        暂无模板（自定义模板需先在流水线中发布）。
      </div>
    </div>

    <el-dialog v-model="importOpen" title="导入 Pipeline DSL" width="560px">
      <el-tabs v-model="importMode">
        <el-tab-pane label="YAML 内容" name="yaml-content">
          <el-input
            v-model="yamlContent"
            type="textarea"
            :rows="12"
            placeholder="粘贴 pipeline YAML…"
          />
        </el-tab-pane>
        <el-tab-pane label="YAML URL" name="yaml-url">
          <el-input v-model="yamlUrl" placeholder="https://..." />
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="importOpen = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="doImport">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  confirmPipelineDslImport,
  createEmptyPipelineDataset,
  createPipelineDatasetFromYaml,
  fetchPipelineTemplateDetail,
  fetchPipelineTemplates,
  importPipelineDsl,
} from '@/features/datasets/api/difyPipelineApi.js'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'

const router = useRouter()
const store = useDatasetStore()
const templateType = ref('built-in')
const templates = ref([])
const loading = ref(false)
const applyingId = ref('')
const creatingEmpty = ref(false)
const importOpen = ref(false)
const importMode = ref('yaml-content')
const yamlContent = ref('')
const yamlUrl = ref('')
const importing = ref(false)

function goPipeline(datasetId) {
  if (!datasetId) {
    router.push('/datasets')
    return
  }
  router.push(`/datasets/${datasetId}/pipeline`)
}

async function loadTemplates() {
  loading.value = true
  try {
    const res = await fetchPipelineTemplates({ type: templateType.value })
    templates.value = res.data || res.pipeline_templates || res.items || []
  }
  catch (e) {
    templates.value = []
    ElMessage.error(e.message || '模板列表加载失败')
  }
  finally {
    loading.value = false
  }
}

async function applyTemplate(item) {
  const id = item.id || item.template_id
  if (!id)
    return
  applyingId.value = id
  try {
    const detail = await fetchPipelineTemplateDetail(id, { type: templateType.value })
    const yaml = detail.export_data || detail.yaml_content || detail.dsl || ''
    if (!yaml)
      throw new Error('模板未返回 YAML 内容')
    const created = await createPipelineDatasetFromYaml({ yaml_content: yaml })
    await store.loadDatasets()
    ElMessage.success('已从模板创建')
    goPipeline(created.dataset_id || created.id)
  }
  catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
  finally {
    applyingId.value = ''
  }
}

async function createEmpty() {
  creatingEmpty.value = true
  try {
    const created = await createEmptyPipelineDataset()
    await store.loadDatasets()
    ElMessage.success('已创建空白流水线知识库')
    goPipeline(created.dataset_id || created.id)
  }
  catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
  finally {
    creatingEmpty.value = false
  }
}

async function doImport() {
  importing.value = true
  try {
    const payload = importMode.value === 'yaml-url'
      ? { mode: 'yaml-url', yaml_url: yamlUrl.value.trim() }
      : { mode: 'yaml-content', yaml_content: yamlContent.value }
    if (importMode.value === 'yaml-url' && !payload.yaml_url)
      throw new Error('请填写 YAML URL')
    if (importMode.value === 'yaml-content' && !payload.yaml_content?.trim())
      throw new Error('请粘贴 YAML 内容')

    const imported = await importPipelineDsl(payload)
    let datasetId = imported.dataset_id || imported.id
    const importId = imported.import_id || imported.id
    if (imported.status === 'completed' && datasetId) {
      // ok
    }
    else if (importId) {
      const confirmed = await confirmPipelineDslImport(importId)
      datasetId = confirmed.dataset_id || confirmed.id || datasetId
    }
    await store.loadDatasets()
    ElMessage.success('导入成功')
    importOpen.value = false
    goPipeline(datasetId)
  }
  catch (e) {
    ElMessage.error(e.message || '导入失败')
  }
  finally {
    importing.value = false
  }
}

onMounted(loadTemplates)
</script>

<style scoped>
.pipeline-create {
  padding: 20px 24px 40px;
  box-sizing: border-box;
  background: #f8fafc;
  min-height: 100%;
}
.back {
  border: none;
  background: transparent;
  color: #667085;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
  margin-bottom: 8px;
}
.page-header h1 {
  margin: 0;
  font-size: 22px;
  color: #101828;
}
.page-header p {
  margin: 6px 0 0;
  font-size: 13px;
  color: #667085;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 16px 0;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  min-height: 120px;
}
.template-card {
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.template-card h3 {
  margin: 0;
  font-size: 15px;
  color: #101828;
}
.template-card p {
  margin: 0;
  flex: 1;
  font-size: 12px;
  color: #667085;
  min-height: 36px;
}
.empty {
  grid-column: 1 / -1;
  text-align: center;
  color: #98a2b3;
  padding: 40px 12px;
}
</style>
