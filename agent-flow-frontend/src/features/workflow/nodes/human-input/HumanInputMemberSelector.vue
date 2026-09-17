<template>
  <div class="member-selector">
    <span class="label">工作区成员</span>
    <el-select
      :model-value="selectedIds"
      multiple
      filterable
      collapse-tags
      collapse-tags-tooltip
      :filter-method="onFilter"
      :loading="loading"
      :disabled="readOnly"
      placeholder="搜索姓名或邮箱"
      @update:model-value="onSelect"
    >
      <el-option
        v-for="member in visibleMembers"
        :key="member.id"
        :label="memberLabel(member)"
        :value="member.id"
      />
    </el-select>
    <div v-if="loadError" class="error-row">
      <span>成员加载失败，重试</span>
      <el-button link type="primary" :disabled="loading" @click="loadMembers">重试</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchWorkspaceMembers } from '../../api/workspaceMembersApi.js'
import {
  filterWorkspaceMembers,
  memberSelectorOptions,
  replaceMemberRecipients,
  selectedMemberIds,
} from './humanInputMembers.js'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])
const members = ref([])
const query = ref('')
const loading = ref(false)
const loadError = ref(false)
const selectedIds = computed(() => selectedMemberIds(props.modelValue))
const visibleMembers = computed(() => filterWorkspaceMembers(
  memberSelectorOptions(members.value, selectedIds.value),
  query.value,
))

function memberLabel(member) {
  if (member.unknown)
    return `${member.id}（未知成员）`
  return member.email ? `${member.name} <${member.email}>` : member.name || member.id
}

function onFilter(value) {
  query.value = value
}

function onSelect(ids) {
  emit('update:modelValue', replaceMemberRecipients(props.modelValue, ids))
}

async function loadMembers() {
  loading.value = true
  loadError.value = false
  try {
    members.value = await fetchWorkspaceMembers()
  }
  catch {
    loadError.value = true
  }
  finally {
    loading.value = false
  }
}

onMounted(loadMembers)
</script>

<style scoped>
.member-selector { display: flex; flex-direction: column; gap: 4px; }
.label { color: #475569; font-size: 11px; font-weight: 600; }
.error-row { display: flex; align-items: center; gap: 8px; color: #b42318; font-size: 12px; }
</style>
