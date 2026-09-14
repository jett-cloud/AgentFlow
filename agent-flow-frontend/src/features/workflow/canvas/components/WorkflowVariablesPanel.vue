<template>
  <aside class="variables-panel" aria-label="工作流变量">
    <header>
      <div>
        <h2>变量</h2>
        <p>管理全局、环境和会话变量</p>
      </div>
      <button type="button" aria-label="关闭变量面板" @click="$emit('close')">×</button>
    </header>

    <nav class="tabs" aria-label="变量类型">
      <button v-for="item in tabs" :key="item.id" type="button" :class="{ active: tab === item.id }" @click="tab = item.id">
        {{ item.label }}
      </button>
    </nav>

    <main>
      <template v-if="tab === 'sys'">
        <p class="tip">全局变量由系统在运行时注入，只读且不需要配置。</p>
        <VariableRow v-for="item in systemVariables" :key="item.name" :item="item" readonly />
      </template>

      <template v-else>
        <div class="section-actions">
          <p>{{ tab === 'env' ? '环境变量可供所有节点引用。敏感值请使用 Secret。' : '会话变量在多轮对话之间保持状态。' }}</p>
          <button type="button" :disabled="readOnly" @click="startCreate">+ 添加</button>
        </div>
        <div v-if="currentVariables.length === 0" class="empty">还没有变量</div>
        <VariableRow
          v-for="item in currentVariables"
          :key="item.id || item.name"
          :item="item"
          :secret="tab === 'env' && item.value_type === 'secret'"
          :readonly="readOnly"
          @edit="startEdit(item)"
          @delete="removeVariable(item)"
        />
      </template>
    </main>

    <div v-if="editing" class="editor">
      <h3>{{ editing.id ? '编辑变量' : '添加变量' }}</h3>
      <label>名称<input v-model.trim="editing.name" autocomplete="off" placeholder="VARIABLE_NAME" /></label>
      <label>
        类型
        <select v-model="editing.value_type">
          <option v-for="type in availableTypes" :key="type" :value="type">{{ type }}</option>
        </select>
      </label>
      <label>默认值<input v-model="editing.value" :type="editing.value_type === 'secret' ? 'password' : 'text'" autocomplete="off" /></label>
      <label>描述<input v-model.trim="editing.description" autocomplete="off" /></label>
      <p v-if="formError" class="form-error">{{ formError }}</p>
      <footer>
        <button type="button" @click="editing = null">取消</button>
        <button type="button" class="save" @click="saveVariable">保存</button>
      </footer>
    </div>
  </aside>
</template>

<script setup>
import { computed, defineComponent, h, inject, ref, toValue } from 'vue'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import { isChatflowMode } from '../../model/appModes.js'
import { getGlobalVars } from '../../model/availableVariables.js'

const props = defineProps({
  readOnly: { type: Boolean, default: false },
  activeTab: {
    type: String,
    default: 'sys',
    validator: value => ['sys', 'env', 'conversation'].includes(value),
  },
})
const emit = defineEmits(['close', 'change', 'update:activeTab'])

const VariableRow = defineComponent({
  props: {
    item: { type: Object, required: true },
    readonly: Boolean,
    secret: Boolean,
  },
  emits: ['edit', 'delete'],
  setup(props, { emit }) {
    return () => h('div', { class: 'variable-row' }, [
      h('div', { class: 'variable-main' }, [
        h('code', `${props.item.prefix || ''}${props.item.name}`),
        h('span', props.item.value_type || 'string'),
        props.item.description ? h('small', props.item.description) : null,
      ]),
      props.secret ? h('strong', '••••••••') : null,
      !props.readonly ? h('div', { class: 'row-actions' }, [
        h('button', { type: 'button', onClick: () => emit('edit') }, '编辑'),
        h('button', { type: 'button', onClick: () => emit('delete') }, '删除'),
      ]) : null,
    ])
  },
})

const store = useWorkflowStore()
const workflowGraph = inject('workflowGraph', null)
const workflowCore = inject('workflowCore', null)
const workflowMode = inject('workflowMode', null)
const tab = computed({
  get: () => props.activeTab,
  set: value => emit('update:activeTab', value),
})
const editing = ref(null)
const originalName = ref('')
const formError = ref('')
const tabs = [
  { id: 'sys', label: '全局变量' },
  { id: 'env', label: '环境变量' },
  { id: 'conversation', label: '会话变量' },
]
const systemVariables = computed(() => {
  const mode = toValue(workflowMode) || 'workflow'
  const isChatMode = isChatflowMode(mode)
  // getGlobalVars already uses full names like sys.user_id
  return getGlobalVars(isChatMode).map(item => ({
    name: item.variable,
    prefix: '',
    value_type: item.type,
    description: item.des,
  }))
})

const currentVariables = computed(() => tab.value === 'env' ? store.environmentVariables : store.conversationVariables)
const availableTypes = computed(() => tab.value === 'env'
  ? ['string', 'number', 'secret']
  : ['string', 'number', 'boolean', 'object', 'array[string]', 'array[number]', 'array[object]'])

function startCreate() {
  originalName.value = ''
  formError.value = ''
  editing.value = { id: '', name: '', value_type: 'string', value: '', description: '' }
}

function startEdit(item) {
  originalName.value = item.name
  formError.value = ''
  editing.value = structuredClone(item)
}

function replaceSelector(value, from, to) {
  if (Array.isArray(value)) {
    if (value.length === 2 && value[0] === from[0] && value[1] === from[1])
      return [...to]
    return value.map(item => replaceSelector(item, from, to))
  }
  if (value && typeof value === 'object') {
    for (const key of Object.keys(value))
      value[key] = replaceSelector(value[key], from, to)
  }
  return value
}

function updateReferences(oldName, newName) {
  if (!oldName || oldName === newName) return
  const namespace = tab.value
  workflowCore?.recordHistory?.()
  for (const node of workflowGraph?.getNodes?.() || [])
    replaceSelector(node.data, [namespace, oldName], newName ? [namespace, newName] : [])
}

function commitVariables(variables) {
  if (tab.value === 'env') store.setEnvironmentVariables(variables)
  else store.setConversationVariables(variables)
  emit('change', {
    environmentVariables: store.environmentVariables,
    conversationVariables: store.conversationVariables,
  })
}

function saveVariable() {
  const name = editing.value?.name?.trim()
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name || '')) {
    formError.value = '名称只能包含字母、数字和下划线，且不能以数字开头'
    return
  }
  if (currentVariables.value.some(item => item.name === name && item.id !== editing.value.id)) {
    formError.value = '变量名称不能重复'
    return
  }
  const variable = { ...editing.value, id: editing.value.id || crypto.randomUUID(), name }
  const next = editing.value.id
    ? currentVariables.value.map(item => item.id === variable.id ? variable : item)
    : [variable, ...currentVariables.value]
  updateReferences(originalName.value, name)
  commitVariables(next)
  editing.value = null
}

function removeVariable(item) {
  updateReferences(item.name, '')
  commitVariables(currentVariables.value.filter(variable => variable.id !== item.id))
}
</script>

<style scoped>
.variables-panel { position:absolute; z-index:70; top:60px; right:8px; bottom:8px; width:420px; overflow:hidden; border:1px solid var(--components-panel-border,#e4e7ec); border-radius:16px; background:var(--components-panel-bg,#fff); box-shadow:0 12px 32px rgb(16 24 40 / 16%); color:#101828; }
header,.section-actions,.variable-row,.editor footer { display:flex; align-items:center; justify-content:space-between; gap:12px; }
header { padding:16px; } h2,h3,p { margin:0; } h2 { font-size:16px; } header p,.tip,.section-actions p { color:#667085; font-size:12px; }
button { border:0; border-radius:7px; background:transparent; padding:6px 8px; cursor:pointer; } button:hover { background:#f2f4f7; }
.tabs { display:flex; gap:4px; padding:0 16px 12px; border-bottom:1px solid #eaecf0; }.tabs button.active { background:#f2f4f7; color:#155eef; font-weight:600; }
main { height:calc(100% - 112px); overflow:auto; padding:16px; }.tip { margin-bottom:12px; }.section-actions { align-items:flex-start; margin-bottom:12px; }.section-actions button,.save { background:#155eef; color:#fff; }
.variable-row { min-height:54px; padding:10px 8px; border-bottom:1px solid #f2f4f7; }:deep(.variable-main) { display:flex; min-width:0; flex-wrap:wrap; align-items:center; gap:6px; }:deep(.variable-main code) { color:#155eef; }:deep(.variable-main span) { border-radius:4px; background:#f2f4f7; padding:2px 5px; color:#667085; font-size:10px; }:deep(.variable-main small) { width:100%; overflow:hidden; color:#667085; text-overflow:ellipsis; white-space:nowrap; }:deep(.row-actions) { display:flex; }:deep(.row-actions button:last-child) { color:#d92d20; }.empty { padding:48px 0; text-align:center; color:#98a2b3; }
.editor { position:absolute; inset:0; z-index:2; padding:20px; background:#fff; }.editor label { display:flex; flex-direction:column; gap:6px; margin-top:16px; color:#475467; font-size:12px; }.editor input,.editor select { height:36px; border:1px solid #d0d5dd; border-radius:8px; padding:0 10px; }.editor footer { margin-top:20px; justify-content:flex-end; }.form-error { margin-top:8px; color:#d92d20; font-size:12px; }
</style>
