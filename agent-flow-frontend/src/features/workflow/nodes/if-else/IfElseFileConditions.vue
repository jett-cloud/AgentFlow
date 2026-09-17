<template>
  <div class="file-conditions">
    <div class="file-condition-header">
      <el-select
        :model-value="subCondition.logical_operator"
        size="small"
        class="logical-select"
        :disabled="readOnly"
        @change="updateLogicalOperator"
      >
        <el-option label="AND" value="and" />
        <el-option label="OR" value="or" />
      </el-select>
      <button v-if="!readOnly" type="button" class="add-button" @click="addCondition">
        添加文件条件
      </button>
    </div>

    <div v-for="item in subCondition.conditions" :key="item.id" class="file-condition-row">
      <el-select
        :model-value="item.key"
        placeholder="文件属性"
        size="small"
        :disabled="readOnly"
        @change="updateKey(item.id, $event)"
      >
        <el-option v-for="field in fields" :key="field.key" :label="field.label" :value="field.key" />
      </el-select>
      <el-select
        :model-value="item.comparison_operator"
        placeholder="比较运算符"
        size="small"
        :disabled="readOnly || !item.key"
        @change="updateItem(item.id, 'comparison_operator', $event)"
      >
        <el-option
          v-for="operator in operators(item)"
          :key="operator.value"
          :label="operator.name"
          :value="operator.value"
        />
      </el-select>
      <IfElseConditionValue
        v-if="isIfElseOperatorValueRequired(item.comparison_operator)"
        :condition="item"
        :read-only="readOnly"
        @update:value="updateItem(item.id, 'value', $event)"
      />
      <button v-if="!readOnly" type="button" class="remove-button" @click="removeCondition(item.id)">
        删除
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import IfElseConditionValue from './IfElseConditionValue.vue'
import {
  createIfElseId,
  createIfElseSubCondition,
  getIfElseOperators,
  isIfElseOperatorValueRequired,
} from './ifElseNode.js'

const props = defineProps({
  condition: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['update:subVariableCondition'])
const fallbackCaseId = createIfElseId()

const fields = [
  { key: 'name', label: '文件名' },
  { key: 'type', label: '文件类型' },
  { key: 'size', label: '文件大小' },
  { key: 'extension', label: '扩展名' },
  { key: 'mime_type', label: 'MIME 类型' },
  { key: 'transfer_method', label: '传输方式' },
  { key: 'url', label: 'URL' },
  { key: 'related_id', label: '关联 ID' },
]

const subCondition = computed(() => props.condition.sub_variable_condition || {
  case_id: fallbackCaseId,
  logical_operator: 'and',
  conditions: [],
})

const emitValue = (value) => emit('update:subVariableCondition', value)

const updateLogicalOperator = (value) => emitValue({ ...subCondition.value, logical_operator: value })

const addCondition = () => emitValue({
  ...subCondition.value,
  conditions: [...subCondition.value.conditions, createIfElseSubCondition()],
})

const removeCondition = id => emitValue({
  ...subCondition.value,
  conditions: subCondition.value.conditions.filter(item => item.id !== id),
})

const updateItem = (id, key, value) => emitValue({
  ...subCondition.value,
  conditions: subCondition.value.conditions.map(item => item.id === id ? { ...item, [key]: value } : item),
})

const updateKey = (id, key) => {
  const replacement = createIfElseSubCondition(key)
  replacement.id = id
  emitValue({
    ...subCondition.value,
    conditions: subCondition.value.conditions.map(item => item.id === id ? replacement : item),
  })
}

const operators = item => getIfElseOperators(item.varType, item.key ? { key: item.key } : undefined)
</script>

<style scoped>
.file-conditions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.file-condition-header,
.file-condition-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.logical-select {
  width: 88px;
}

.add-button,
.remove-button {
  border: 0;
  background: transparent;
  color: #475467;
  cursor: pointer;
  white-space: nowrap;
}

.remove-button {
  color: #d92d20;
}
</style>
