// src/views/copilot/components/workflow/node/human-input/useHumanInputConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import {
  createDeliveryMethodId,
  createHumanInputField,
  getHumanInputBranches,
  mergeHumanInputPatch,
  normalizeHumanInputData,
  normalizeHumanInputEmailConfig,
} from './humanInputNode.js'

export const FORM_INPUT_TYPES = [
  { value: 'paragraph', label: '多行文本' },
  { value: 'select', label: '下拉选择' },
  { value: 'file', label: '单文件上传' },
  { value: 'file-list', label: '多文件上传' },
]

export const BUTTON_STYLES = [
  { value: 'primary', label: '主要' },
  { value: 'default', label: '默认' },
  { value: 'accent', label: '强调' },
  { value: 'ghost', label: '幽灵' },
]

export function useHumanInputConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  let pendingPatch = null
  const patch = (partial) => {
    pendingPatch = mergeHumanInputPatch(nodeData.value, pendingPatch, partial)
    emit('update:nodeData', pendingPatch)
    queueMicrotask(() => {
      pendingPatch = null
    })
  }

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
      patch({ delivery_methods: [...allTypes].map(type => ({ ...(current.find(item => item.type === type) || {}), id: current.find(item => item.type === type)?.id || createDeliveryMethodId(), type, enabled: types.includes(type) })) })
    }
  })

  const emailConfig = computed({
    get: () => {
      const email = normalizeHumanInputData(nodeData.value).delivery_methods.find(item => item.type === 'email')
      return normalizeHumanInputEmailConfig(email?.config)
    },
    set: (config) => {
      const normalized = normalizeHumanInputData(nodeData.value)
      patch({
        delivery_methods: normalized.delivery_methods.map(item => (
          item.type === 'email'
            ? { ...item, config: normalizeHumanInputEmailConfig(config) }
            : item
        )),
      })
    },
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
    get: () => Number(nodeData.value?.timeout) || 3,
    set: val => patch({ timeout: val })
  })

  const timeoutUnit = computed({
    get: () => nodeData.value?.timeout_unit === 'hour' ? 'hour' : 'day',
    set: val => patch({ timeout_unit: val })
  })

  const targetBranches = computed(() => getHumanInputBranches(normalizeHumanInputData(nodeData.value)))

  // 添加表单字段 (映射为 Dify 变量配置: output_variable_name)
  const addFormInput = () => {
    const usedNames = new Set(inputs.value.map(item => item.output_variable_name))
    let idx = inputs.value.length + 1
    while (usedNames.has(`field_${idx}`))
      idx += 1
    const newList = [
      ...inputs.value,
      createHumanInputField('paragraph', `field_${idx}`),
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
    emailConfig,
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
