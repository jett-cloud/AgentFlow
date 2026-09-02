<template>
  <div v-if="visible" class="modal-mask" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-modal="true">
      <header>
        <div>
          <h3>{{ title }}</h3>
          <p>可新增、修改或删除已保存的 API Key。工作流节点只选择模型，不保存密钥。</p>
        </div>
        <button type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="body">
        <div v-if="availableCredentials.length" class="cred-list">
          <h4>已有凭证</h4>
          <ul>
            <li v-for="cred in availableCredentials" :key="cred.credential_id || cred.id">
              <strong>{{ cred.credential_name || cred.name || cred.credential_id || cred.id }}</strong>
              <div class="cred-actions">
                <button type="button" class="link" :disabled="saving" @click="startEdit(cred)">编辑</button>
                <button type="button" class="link danger" :disabled="saving" @click="handleDelete(cred)">删除</button>
              </div>
            </li>
          </ul>
        </div>

        <h4>{{ editingCredentialId ? '修改凭证' : '新增凭证' }}</h4>
        <CredentialSchemaFields
          :fields="formFields"
          :model-value="formValues"
          :disabled="saving"
          @update:model-value="onFormValuesUpdate"
        />

        <label class="field">
          <span>凭证名称（可选）</span>
          <input v-model="credentialName" type="text" placeholder="API KEY 1" autocomplete="off">
        </label>

        <p v-if="message" class="msg" :class="{ error: isError }">{{ message }}</p>
      </div>

      <footer>
        <button v-if="editingCredentialId" type="button" :disabled="saving" @click="resetForm">取消编辑</button>
        <button type="button" :disabled="saving" @click="handleValidate">校验</button>
        <button type="button" class="primary" :disabled="saving" @click="handleSave">
          {{ saving ? '保存中…' : (editingCredentialId ? '更新' : '保存') }}
        </button>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createProviderCredential,
  deleteProviderCredential,
  updateProviderCredential,
  validateProviderCredential,
} from '@/features/integrations/api/difyModelsApi.js'
import { providerLabel } from '../lib/modelProviderHelpers.js'
import {
  buildCredentialsPayload,
  buildInitialCredentialFormValues,
  normalizeCredentialFormFields,
} from '../lib/credentialFormHelpers.js'
import CredentialSchemaFields from './CredentialSchemaFields.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  provider: { type: Object, default: null },
})

const emit = defineEmits(['close', 'saved'])

const formValues = reactive({})
const credentialName = ref('')
const editingCredentialId = ref('')
const saving = ref(false)
const message = ref('')
const isError = ref(false)

const title = computed(() => (props.provider ? `配置 ${providerLabel(props.provider)}` : '配置凭证'))

const availableCredentials = computed(() => {
  const custom = props.provider?.custom_configuration
  const list = custom?.available_credentials
    || custom?.provider?.available_credentials
    || props.provider?.available_credentials
    || []
  return Array.isArray(list) ? list : []
})

const formFields = computed(() => {
  const schemas = props.provider?.provider_credential_schema?.credential_form_schemas || []
  const fields = normalizeCredentialFormFields(schemas)
  if (fields.length)
    return fields
  return normalizeCredentialFormFields([{
    variable: 'api_key',
    label: 'API Key',
    type: 'secret-input',
    placeholder: 'sk-...',
    required: true,
  }])
})

function applyInitialValues() {
  Object.keys(formValues).forEach(key => delete formValues[key])
  Object.assign(formValues, buildInitialCredentialFormValues(formFields.value))
}

function onFormValuesUpdate(next) {
  Object.keys(formValues).forEach(key => delete formValues[key])
  Object.assign(formValues, next || {})
}

function resetForm() {
  editingCredentialId.value = ''
  credentialName.value = ''
  message.value = ''
  isError.value = false
  applyInitialValues()
}

watch(
  () => [props.visible, props.provider?.provider],
  ([visible]) => {
    if (visible)
      resetForm()
  },
)

function buildCredentials() {
  return buildCredentialsPayload(formFields.value, formValues, {
    editing: !!editingCredentialId.value,
  })
}

function startEdit(cred) {
  editingCredentialId.value = cred.credential_id || cred.id
  credentialName.value = cred.credential_name || cred.name || ''
  message.value = '编辑时请重新填写密钥字段后保存'
  isError.value = false
  applyInitialValues()
}

async function handleValidate() {
  if (!props.provider) return
  saving.value = true
  message.value = ''
  isError.value = false
  try {
    await validateProviderCredential(props.provider.provider, {
      credentials: buildCredentials(),
    })
    message.value = '校验通过'
  }
  catch (e) {
    isError.value = true
    message.value = e.response?.data?.message || e.message || '校验失败'
  }
  finally {
    saving.value = false
  }
}

async function handleSave() {
  if (!props.provider) return
  saving.value = true
  message.value = ''
  isError.value = false
  try {
    const credentials = buildCredentials()
    if (editingCredentialId.value) {
      await updateProviderCredential(props.provider.provider, {
        credential_id: editingCredentialId.value,
        name: credentialName.value || undefined,
        credentials,
      })
      ElMessage.success('凭证已更新')
    }
    else {
      await createProviderCredential(props.provider.provider, {
        name: credentialName.value || undefined,
        credentials,
      })
      ElMessage.success('模型提供商凭证已保存')
    }
    emit('saved')
    emit('close')
  }
  catch (e) {
    isError.value = true
    message.value = e.response?.data?.message || e.message || '保存失败'
  }
  finally {
    saving.value = false
  }
}

async function handleDelete(cred) {
  if (!props.provider) return
  const id = cred.credential_id || cred.id
  try {
    await ElMessageBox.confirm(
      `确定删除凭证「${cred.credential_name || cred.name || id}」？`,
      '删除凭证',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  }
  catch {
    return
  }
  saving.value = true
  try {
    await deleteProviderCredential(props.provider.provider, { credential_id: id })
    ElMessage.success('凭证已删除')
    emit('saved')
  }
  catch (e) {
    ElMessage.error(e.response?.data?.message || e.message || '删除失败')
  }
  finally {
    saving.value = false
  }
}
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgb(16 24 40 / 45%);
  padding: 16px;
}
.modal {
  width: min(520px, 100%);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 20px 48px rgb(16 24 40 / 18%);
  overflow: hidden;
}
header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid #eaecf0;
}
header h3, header p { margin: 0; }
header h3 { font-size: 16px; color: #101828; }
header p { margin-top: 4px; font-size: 12px; color: #667085; }
header button {
  border: 0;
  background: transparent;
  font-size: 20px;
  cursor: pointer;
  color: #667085;
}
.body {
  padding: 16px;
  max-height: min(60vh, 480px);
  overflow: auto;
}
.cred-list { margin-bottom: 16px; }
.cred-list h4, .body > h4 { margin: 0 0 8px; font-size: 13px; color: #344054; }
.cred-list ul { margin: 0; padding: 0; list-style: none; }
.cred-list li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f2f4f7;
  font-size: 13px;
}
.cred-actions { display: flex; gap: 8px; }
.link {
  border: 0;
  background: transparent;
  color: var(--af-brand-strong);
  cursor: pointer;
  font-size: 12px;
}
.link.danger { color: #b42318; }
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #344054;
}
.field input {
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}
.msg { margin: 0; font-size: 12px; color: #027a48; }
.msg.error { color: #b42318; }
footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px 16px;
  border-top: 1px solid #eaecf0;
}
footer button {
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  background: #fff;
  padding: 8px 14px;
  cursor: pointer;
}
footer .primary {
  border-color: var(--af-brand);
  background: var(--af-brand);
  color: #fff;
}
</style>
