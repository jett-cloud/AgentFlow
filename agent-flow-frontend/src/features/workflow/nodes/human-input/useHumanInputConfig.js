// src/views/copilot/components/workflow/node/human-input/useHumanInputConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { normalizeHumanInputData } from './humanInputNode.js'

export const FORM_INPUT_TYPES = [
  { value: 'text', label: '单行文本 (Text)' },
  { value: 'paragraph', label: '多行文本 (Paragraph)' },
  { value: 'select', label: '下拉选择 (Select)' },
  { value: 'file', label: '单文件上传 (File)' },
  { value: 'files', label: '多文件上传 (File List)' }
]

export const BUTTON_STYLES = [
  { value: 'primary', label: '主要 (Primary)' },
  { value: 'default', label: '默认 (Default)' },
  { value: 'danger', label: '危险/拒绝 (Danger)' }
]

export function useHumanInputConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const patch = partial => emit('update:nodeData', { ...normalizeHumanInputData(nodeData.value), ...partial })

  // 1. 交互提示词 (form_content / prompt)
  const prompt = computed({
    get: () => nodeData.value?.form_content || '',
    set: val => patch({ form_content: val })
  })

  // 2. 交付/通知渠道 (delivery_methods)
  const deliveryMethods = computed({
    get: () => normalizeHumanInputData(nodeData.value).delivery_methods.filter(item => item.enabled).map(item => item.type),
    set: (types) => {
      const current = normalizeHumanInputData(nodeData.value).delivery_methods
      const allTypes = new Set([...current.map(item => item.type), ...(types || [])])
      patch({ delivery_methods: [...allTypes].map((type, index) => ({ ...(current.find(item => item.type === type) || {}), id: current.find(item => item.type === type)?.id || `delivery-${type}-${index}`, type, enabled: types.includes(type) })) })
    }
  })

  // 3. 人类填报字段列表 (Dify 内部模型字段名为 inputs)
  const inputs = computed({
    get: () => normalizeHumanInputData(nodeData.value).inputs,
    set: val => patch({ inputs: val })
  })

  // 4. 人工操作按钮/分支 (user_actions)
  const userActions = computed({
    get: () => normalizeHumanInputData(nodeData.value).user_actions,
    set: val => patch({ user_actions: val })
  })

  // 5. 超时时间 (timeout & timeout_unit)
  const timeout = computed({
    get: () => nodeData.value?.timeout || 24,
    set: val => patch({ timeout: val })
  })

  const timeoutUnit = computed({
    get: () => nodeData.value?.timeout_unit || 'hour',
    set: val => patch({ timeout_unit: val })
  })

  // 6. 右侧连线分支（动态动作按钮分支 + 固定超时分支）
  const targetBranches = computed(() => {
    const actions = (userActions.value || []).map(action => ({
      id: action.id,
      name: action.title || action.id,
      style: action.button_style || 'primary'
    }))
    return [
      ...actions,
      { id: '__timeout', name: 'Timeout (超时)', isTimeout: true }
    ]
  })

  // 添加表单字段 (映射为 Dify 变量配置: output_variable_name)
  const addFormInput = () => {
    const idx = inputs.value.length + 1
    const newList = [
      ...inputs.value,
      {
        output_variable_name: `field_${idx}`,
        label: `输入项 ${idx}`,
        type: 'text',
        required: true,
        default_value: ''
      }
    ]
    inputs.value = newList
  }

  // 删除表单字段
  const removeFormInput = (index) => {
    const newList = [...inputs.value]
    newList.splice(index, 1)
    inputs.value = newList
  }

  // 添加操作按钮
  const addUserAction = () => {
    const newList = [
      ...userActions.value,
      {
        id: `action_${Date.now()}`,
        title: '',
        button_style: 'default'
      }
    ]
    userActions.value = newList
  }

  // 删除操作按钮
  const removeUserAction = (index) => {
    const newList = [...userActions.value]
    newList.splice(index, 1)
    userActions.value = newList
  }

  const updateUserAction = (index, partial) => {
    userActions.value = userActions.value.map((item, i) => i === index ? { ...item, ...partial } : item)
  }

  return {
    readOnly,
    prompt,
    deliveryMethods,
    inputs,
    userActions,
    timeout,
    timeoutUnit,
    targetBranches,
    addFormInput,
    removeFormInput,
    addUserAction,
    removeUserAction,
    updateUserAction,
  }
}
