<template>
  <el-dialog
    :model-value="visible"
    :title="`配置 ${providerLabel || '工具'} 凭证`"
    width="min(520px, calc(100vw - 32px))"
    append-to-body
    class="workflow-dialog"
    @update:model-value="emit('update:visible', $event)"
  >
    <div class="credential-dialog-body">
      <p class="dialog-hint">凭证保存到工作区安全存储中，工作流只会保存它的引用。</p>
      <CredentialSchemaFields
        v-if="fields.length"
        :fields="fields"
        :model-value="formValues"
        :disabled="saving || loading"
        @update:model-value="updateValues"
      />
      <p v-else-if="!loading" class="dialog-hint">该工具不需要额外的 API 凭证。</p>
      <label v-if="fields.length" class="name-field">
        <span>凭证名称（可选）</span>
        <input v-model="credentialName" :disabled="saving" placeholder="例如：生产环境" autocomplete="off">
      </label>
      <p v-if="error" class="dialog-error">{{ error }}</p>
    </div>
    <template #footer>
      <button type="button" class="dialog-secondary" :disabled="saving" @click="emit('update:visible', false)">取消</button>
      <button type="button" class="dialog-primary" :disabled="saving || loading || !fields.length" @click="save">
        {{ saving ? '保存中…' : '保存并使用' }}
      </button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import {
  addBuiltinCredential,
  fetchBuiltinCredentialInfo,
  fetchBuiltinCredentialSchema,
  fetchBuiltinCredentials,
  unwrapCredentialList,
} from '@/features/integrations/api/difyToolsApi.js'
import CredentialSchemaFields from '@/features/integrations/ui/CredentialSchemaFields.vue'
import {
  buildCredentialsPayload,
  buildInitialCredentialFormValues,
  normalizeCredentialFormFields,
} from '@/features/integrations/lib/credentialFormHelpers.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  provider: { type: String, default: '' },
  providerLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:visible', 'saved'])

const fields = ref([])
const formValues = reactive({})
const credentialName = ref('')
const credentialType = ref('api-key')
const loading = ref(false)
const saving = ref(false)
const error = ref('')

watch(() => [props.visible, props.provider], ([visible, provider]) => {
  if (visible && provider)
    loadSchema()
}, { immediate: true })

function replaceValues(next) {
  Object.keys(formValues).forEach(key => delete formValues[key])
  Object.assign(formValues, next || {})
}

function updateValues(next) {
  replaceValues(next)
}

async function loadSchema() {
  loading.value = true
  error.value = ''
  credentialName.value = ''
  try {
    const info = await fetchBuiltinCredentialInfo(props.provider, { silent: true })
    const types = info?.supported_credential_types || info?.data?.supported_credential_types || []
    credentialType.value = types.includes('api-key') ? 'api-key' : (types[0] || 'api-key')
    const schema = await fetchBuiltinCredentialSchema(props.provider, credentialType.value)
    fields.value = normalizeCredentialFormFields(schema)
    replaceValues(buildInitialCredentialFormValues(fields.value))
  }
  catch (cause) {
    fields.value = []
    error.value = cause?.response?.data?.message || cause?.message || '加载凭证表单失败'
  }
  finally {
    loading.value = false
  }
}

async function save() {
  if (!props.provider || !fields.value.length)
    return
  saving.value = true
  error.value = ''
  try {
    const before = new Set(unwrapCredentialList(await fetchBuiltinCredentials(props.provider)).map(item => item.id))
    await addBuiltinCredential(props.provider, {
      credentials: buildCredentialsPayload(fields.value, formValues),
      name: credentialName.value || undefined,
      type: credentialType.value,
    })
    const credentials = unwrapCredentialList(await fetchBuiltinCredentials(props.provider))
    const created = credentials.find(item => !before.has(item.id)) || credentials.find(item => item.is_default) || credentials[0]
    if (!created?.id)
      throw new Error('凭证已保存，但未能读取新凭证')
    emit('saved', { credentialId: created.id, credentials })
    emit('update:visible', false)
  }
  catch (cause) {
    error.value = cause?.response?.data?.message || cause?.message || '保存凭证失败'
  }
  finally {
    saving.value = false
  }
}
</script>

<style scoped>
.credential-dialog-body { display: flex; min-height: 0; flex-direction: column; gap: 14px; }
.dialog-hint { margin: 0; color: #667085; font-size: 12px; line-height: 1.5; }
.dialog-error { margin: 0; color: #b42318; font-size: 12px; }
.name-field { display: flex; flex-direction: column; gap: 6px; color: #344054; font-size: 12px; font-weight: 600; }
.name-field input { height: 34px; border: 1px solid #d0d5dd; border-radius: 7px; padding: 0 9px; color: #101828; outline: none; }
.name-field input:focus { border-color: #175cd3; box-shadow: 0 0 0 3px rgb(23 92 211 / 12%); }
.dialog-secondary, .dialog-primary { min-width: 76px; padding: 7px 12px; border-radius: 8px; font-size: 12px; cursor: pointer; }
.dialog-secondary { margin-right: 8px; border: 1px solid #d0d5dd; background: #fff; color: #344054; }
.dialog-primary { border: 1px solid #175cd3; background: #175cd3; color: #fff; }
.dialog-primary:disabled, .dialog-secondary:disabled { cursor: not-allowed; opacity: .6; }
</style>
