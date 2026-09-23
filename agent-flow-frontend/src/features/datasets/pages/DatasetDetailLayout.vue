<template>
  <div class="dataset-detail" v-loading="loading">
    <aside class="side-nav">
      <button type="button" class="back" @click="$router.push('/datasets')">← 知识库</button>
      <h2 class="name">{{ dataset?.name || '…' }}</h2>
      <p class="sub">{{ dataset?.description || '暂无描述' }}</p>
      <nav>
        <RouterLink
          v-for="tab in tabs"
          :key="tab.name"
          :to="tab.to"
          class="nav-item"
          :class="{ active: isActive(tab) }"
        >
          {{ tab.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="detail-main" :class="{ 'is-pipeline': isPipelineEditor }">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDatasetStore } from '@/features/datasets/state/useDatasetStore.js'
import { isExternalDataset, shouldRedirectExternalDataset } from '@/features/datasets/model/hitTestingRequest.js'
import { visibleDatasetTabs } from '@/features/datasets/model/datasetCapabilities.js'

const route = useRoute()
const router = useRouter()
const store = useDatasetStore()
const loading = ref(false)
const dataset = computed(() => store.currentDataset)
const isPipelineEditor = computed(() => route.name === 'dataset-pipeline')
const isExternal = computed(() => isExternalDataset(dataset.value))

const tabs = computed(() => visibleDatasetTabs({
  datasetId: route.params.datasetId,
  isExternal: isExternal.value,
}))

function isActive(tab) {
  return route.name === tab.name
    || (tab.name === 'dataset-documents' && String(route.name || '').startsWith('dataset-document'))
}

async function load() {
  const id = route.params.datasetId
  if (!id)
    return
  loading.value = true
  try {
    const ds = await store.loadDatasetDetail(id)
    if (shouldRedirectExternalDataset(route.name, isExternalDataset(ds))) {
      router.replace(`/datasets/${id}/hitTesting`)
      return
    }
    // Parity with Dify: unpublished rag_pipeline datasets land on pipeline editor.
    if (
      ds?.runtime_mode === 'rag_pipeline'
      && ds?.is_published === false
      && route.name !== 'dataset-pipeline'
      && !String(route.name || '').startsWith('dataset-document')
    ) {
      // only auto-redirect from default documents landing
      if (route.name === 'dataset-documents')
        router.replace(`/datasets/${id}/pipeline`)
    }
  }
  finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => route.params.datasetId, load)
watch(() => route.name, (name) => {
  if (shouldRedirectExternalDataset(name, isExternal.value))
    router.replace(`/datasets/${route.params.datasetId}/hitTesting`)
})
</script>

<style scoped>
.dataset-detail {
  display: flex;
  height: 100%;
  background: #f8fafc;
  min-height: 0;
}
.side-nav {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid #eaecf0;
  background: #fff;
  padding: 16px 12px;
  box-sizing: border-box;
  overflow: auto;
}
.back {
  border: none;
  background: transparent;
  color: #667085;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
  margin-bottom: 12px;
}
.name {
  margin: 0 0 4px;
  font-size: 16px;
  color: #101828;
  word-break: break-word;
}
.sub {
  margin: 0 0 16px;
  font-size: 12px;
  color: #98a2b3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.nav-item {
  display: block;
  padding: 8px 10px;
  border-radius: 8px;
  color: #475467;
  text-decoration: none;
  font-size: 13px;
  margin-bottom: 2px;
}
.nav-item:hover {
  background: #f2f4f7;
}
.nav-item.active {
  background: #eff4ff;
  color: #3538cd;
  font-weight: 600;
}
.detail-main {
  flex: 1;
  min-width: 0;
  overflow: auto;
}
.detail-main.is-pipeline {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.detail-main.is-pipeline > * {
  flex: 1;
  min-height: 0;
}
</style>
