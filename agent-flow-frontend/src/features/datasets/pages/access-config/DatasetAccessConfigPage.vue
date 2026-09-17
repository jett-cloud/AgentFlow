<template>
  <div class="access-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h1>访问控制</h1>
        <p>设置谁可以访问此知识库。对齐 Dify access-config（RBAC 优先，失败时回退经典权限）。</p>
      </div>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </header>

    <el-alert
      v-if="mode === 'classic'"
      type="info"
      :closable="false"
      title="当前工作区未启用数据集 RBAC，已使用经典 permission 字段。"
      class="mb"
    />
    <el-alert
      v-if="rbacError"
      type="warning"
      :closable="false"
      :title="rbacError"
      class="mb"
    />

    <section class="card">
      <h2>开放范围</h2>
      <el-radio-group v-model="scope" class="scope-list">
        <el-radio
          v-for="opt in scopeOptions"
          :key="opt.value"
          :value="opt.value"
          border
          class="scope-item"
        >
          <div>
            <strong>{{ opt.label }}</strong>
            <p>{{ opt.desc }}</p>
          </div>
        </el-radio>
      </el-radio-group>
    </section>

    <section v-if="mode === 'rbac' && (scope === 'specific' || scope === 'all')" class="card">
      <div class="card-head">
        <h2>成员权限</h2>
        <el-button size="small" @click="openAddMember">添加成员</el-button>
      </div>
      <el-table :data="userRows" empty-text="暂无单独配置的成员">
        <el-table-column label="成员" min-width="180">
          <template #default="{ row }">
            <div>{{ row.account?.account_name || row.account?.name || '—' }}</div>
            <div class="email">{{ row.account?.email }}</div>
          </template>
        </el-table-column>
        <el-table-column label="策略" min-width="200">
          <template #default="{ row }">
            <el-select
              :model-value="row.access_policies?.[0]?.id || ''"
              placeholder="选择策略"
              style="width: 100%"
              @update:model-value="id => onChangePolicy(row, id)"
            >
              <el-option
                v-for="p in policyOptions"
                :key="p.id"
                :label="p.name"
                :value="p.id"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button link type="danger" @click="removeMember(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="addOpen" title="添加成员" width="420px">
      <el-select v-model="addMemberId" filterable placeholder="选择成员" style="width: 100%">
        <el-option
          v-for="m in availableMembers"
          :key="m.id"
          :label="`${m.name || m.account_name || m.email} (${m.email || ''})`"
          :value="m.id"
        />
      </el-select>
      <el-select
        v-model="addPolicyId"
        placeholder="选择策略"
        style="width: 100%; margin-top: 12px"
      >
        <el-option
          v-for="p in policyOptions"
          :key="p.id"
          :label="p.name"
          :value="p.id"
        />
      </el-select>
      <template #footer>
        <el-button @click="addOpen = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="confirmAddMember">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchDatasetAccessPolicy,
  fetchDatasetUserAccessPolicies,
  fetchWorkspaceMembers,
  removeDatasetAccessPolicyMembers,
  updateDatasetOpenScope,
  updateDatasetUserAccessPolicies,
} from '@/features/datasets/api/difyAccessControlApi.js'
import { fetchDatasetDetail, updateDataset } from '@/features/datasets/api/difyDatasetsApi.js'

const RBAC_SCOPES = [
  { value: 'all', label: '所有有权限的成员', desc: '工作区内具备策略的成员均可访问' },
  { value: 'only_me', label: '仅自己', desc: '只有你本人可以访问' },
  { value: 'specific', label: '指定成员', desc: '仅下列成员可访问' },
]

const CLASSIC_SCOPES = [
  { value: 'all_team_members', label: '团队所有成员', desc: '工作区全部成员可访问' },
  { value: 'only_me', label: '仅自己', desc: '只有你本人可以访问' },
  { value: 'partial_members', label: '部分成员', desc: '仅指定成员（需在后端配置 partial_member_list）' },
]

const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const mode = ref('classic')
const rbacError = ref('')
const scope = ref('only_me')
const userRows = ref([])
const policyOptions = ref([])
const members = ref([])
const addOpen = ref(false)
const addMemberId = ref('')
const addPolicyId = ref('')
const adding = ref(false)
const classicPermission = ref('only_me')

const scopeOptions = computed(() => (mode.value === 'rbac' ? RBAC_SCOPES : CLASSIC_SCOPES))

const availableMembers = computed(() => {
  const used = new Set(userRows.value.map(r => r.account?.id).filter(Boolean))
  return members.value.filter(m => m.id && !used.has(m.id))
})

function datasetId() {
  return route.params.datasetId
}

async function loadClassic() {
  mode.value = 'classic'
  const ds = await fetchDatasetDetail(datasetId())
  classicPermission.value = ds.permission || 'only_me'
  scope.value = classicPermission.value
}

async function loadRbac() {
  const [policiesRes, usersRes] = await Promise.all([
    fetchDatasetAccessPolicy(datasetId()),
    fetchDatasetUserAccessPolicies(datasetId()),
  ])
  mode.value = 'rbac'
  rbacError.value = ''
  policyOptions.value = (policiesRes?.items || [])
    .map(item => item.policy || item)
    .filter(p => p?.id)
  userRows.value = usersRes?.data || []
  scope.value = usersRes?.scope || 'only_me'
}

async function loadMembers() {
  try {
    const res = await fetchWorkspaceMembers()
    members.value = res.accounts || res.data || res || []
    if (!Array.isArray(members.value))
      members.value = []
  }
  catch {
    members.value = []
  }
}

async function load() {
  loading.value = true
  rbacError.value = ''
  try {
    await loadRbac()
  }
  catch (e) {
    rbacError.value = e.message || 'RBAC 不可用，已回退经典权限'
    try {
      await loadClassic()
    }
    catch (err) {
      ElMessage.error(err.message || '加载失败')
    }
  }
  finally {
    loading.value = false
  }
  await loadMembers()
}

async function save() {
  saving.value = true
  try {
    if (mode.value === 'rbac') {
      await updateDatasetOpenScope(datasetId(), scope.value)
      ElMessage.success('开放范围已保存')
    }
    else {
      await updateDataset(datasetId(), { permission: scope.value })
      ElMessage.success('权限已保存')
    }
    await load()
  }
  catch (e) {
    ElMessage.error(e.message || '保存失败')
  }
  finally {
    saving.value = false
  }
}

function openAddMember() {
  addMemberId.value = availableMembers.value[0]?.id || ''
  addPolicyId.value = policyOptions.value[0]?.id || ''
  addOpen.value = true
}

async function confirmAddMember() {
  if (!addMemberId.value || !addPolicyId.value) {
    ElMessage.warning('请选择成员与策略')
    return
  }
  adding.value = true
  try {
    await updateDatasetUserAccessPolicies(datasetId(), addMemberId.value, [addPolicyId.value])
    ElMessage.success('已添加')
    addOpen.value = false
    await load()
  }
  catch (e) {
    ElMessage.error(e.message || '添加失败')
  }
  finally {
    adding.value = false
  }
}

async function onChangePolicy(row, policyId) {
  const accountId = row.account?.id
  if (!accountId || !policyId)
    return
  try {
    await updateDatasetUserAccessPolicies(datasetId(), accountId, [policyId])
    ElMessage.success('已更新策略')
    await load()
  }
  catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function removeMember(row) {
  const accountId = row.account?.id
  const policyId = row.access_policies?.[0]?.id
  if (!accountId || !policyId)
    return
  try {
    await ElMessageBox.confirm('确认移除该成员访问权限？', '移除成员', { type: 'warning' })
    await removeDatasetAccessPolicyMembers(datasetId(), policyId, [accountId])
    ElMessage.success('已移除')
    await load()
  }
  catch (e) {
    if (e !== 'cancel' && e?.message)
      ElMessage.error(e.message)
  }
}

onMounted(load)
watch(() => route.params.datasetId, load)
</script>

<style scoped>
.access-page {
  padding: 20px 24px 40px;
  box-sizing: border-box;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}
.page-header h1 {
  margin: 0;
  font-size: 20px;
  color: #101828;
}
.page-header p {
  margin: 6px 0 0;
  font-size: 13px;
  color: #667085;
}
.mb { margin-bottom: 12px; }
.card {
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 14px;
}
.card h2 {
  margin: 0 0 12px;
  font-size: 15px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.card-head h2 { margin: 0; }
.scope-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}
.scope-item {
  width: 100%;
  height: auto;
  margin: 0 !important;
  padding: 12px;
  align-items: flex-start;
}
.scope-item p {
  margin: 4px 0 0;
  font-size: 12px;
  color: #667085;
  font-weight: 400;
  white-space: normal;
}
.email {
  font-size: 12px;
  color: #98a2b3;
}
</style>
