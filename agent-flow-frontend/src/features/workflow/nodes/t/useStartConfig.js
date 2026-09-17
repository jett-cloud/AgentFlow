// src/views/copilot/components/workflow/node/start/useStartConfig.js
import { reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { createStartVariable, InputVarType } from './startNode.js'

export { InputVarType }

/**
 * 对应 Dify 官方选项下拉菜单列表 (buildSelectOptions)
 */
export const INPUT_VAR_TYPE_OPTIONS = [
  { name: '短文本 (Text)', value: InputVarType.textInput, tag: 'String' },
  { name: '长文本 (Paragraph)', value: InputVarType.paragraph, tag: 'Paragraph' },
  { name: '单选下拉 (Select)', value: InputVarType.select, tag: 'Select' },
  { name: '数字 (Number)', value: InputVarType.number, tag: 'Number' },
  { name: '复选框 (Checkbox)', value: InputVarType.checkbox, tag: 'Boolean' },
  { name: '单文件 (Single File)', value: InputVarType.singleFile, tag: 'File' },
  { name: '多文件 (Multi Files)', value: InputVarType.multiFiles, tag: 'Array[File]' },
  { name: 'JSON 对象 (JSON)', value: InputVarType.jsonObject, tag: 'Object' }
]

export function formatVarTypeTag(type) {
  if (!type) return 'String'
  const target = INPUT_VAR_TYPE_OPTIONS.find(t => t.value === type || t.value === type.toLowerCase())
  return target ? target.tag : type
}

/**
 * 对应 Dify 源码 createPayloadForType() 工厂函数：按类型初始化标准 Payload
 */
export function createPayloadForType(variableName = '', type = InputVarType.textInput) {
  return createStartVariable(variableName, type)
}

/**
 * Vue 3 版本的 useStartConfig Hook
 */
export function useStartConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => Boolean(props.readOnly || nodeData.value?.readOnly))
  const isChatMode = computed(() => props.appMode !== 'workflow')

  // 初始化 variables 输入变量列表
  const variables = reactive(
    nodeData.value?.variables && Array.isArray(nodeData.value.variables)
      ? [...nodeData.value.variables]
      : [
          createPayloadForType('query', InputVarType.textInput)
        ]
  )

  // 触发全局节点数据更新
  const notifyChange = () => {
    emit('update:nodeData', {
      ...nodeData.value,
      variables: [...variables]
    })
  }

  // 添加变量 (1:1 对标 Dify validateConfigModalPayload 校验)
  const handleAddVariable = (payloadToSave) => {
    if (!payloadToSave || !payloadToSave.variable) {
      ElMessage.warning('变量 Key (varName) 不能为空')
      return false
    }

    if (!payloadToSave.label) {
      ElMessage.warning('显示名称 (labelName) 不能为空')
      return false
    }

    // 校验 key 是否重复
    const exists = variables.some(v => v.variable === payloadToSave.variable)
    if (exists) {
      ElMessage.error(`变量 Key "${payloadToSave.variable}" 已存在`)
      return false
    }

    // select 类型校验 options
    if (payloadToSave.type === InputVarType.select && (!payloadToSave.options || !payloadToSave.options.length)) {
      ElMessage.error('下拉选择类型至少需要提供一个选项')
      return false
    }

    // jsonObject 类型校验 json_schema
    if (payloadToSave.type === InputVarType.jsonObject && payloadToSave.json_schema) {
      try {
        const parsed = JSON.parse(payloadToSave.json_schema)
        if (parsed?.type !== 'object') {
          ElMessage.error('JSON Schema 顶级 type 必须为 "object"')
          return false
        }
      } catch {
        ElMessage.error('JSON Schema 格式非合法的 JSON')
        return false
      }
    }

    variables.push({ ...payloadToSave })
    notifyChange()
    return true
  }

  // 删除变量
  const handleRemoveVariable = (index) => {
    if (readOnly.value) return
    if (index >= 0 && index < variables.length) {
      variables.splice(index, 1)
      notifyChange()
    }
  }

  // 更新变量
  const handleUpdateVariable = (index, updatedPayload) => {
    if (readOnly.value) return
    if (index >= 0 && index < variables.length) {
      Object.assign(variables[index], updatedPayload)
      notifyChange()
    }
  }

  return {
    readOnly,
    isChatMode,
    variables,
    handleAddVariable,
    handleRemoveVariable,
    handleUpdateVariable,
    notifyChange
  }
}
