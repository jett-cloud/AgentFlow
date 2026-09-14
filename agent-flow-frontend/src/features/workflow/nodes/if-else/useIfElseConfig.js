// src/views/copilot/components/workflow/node/if-else/useIfElseConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { parseSelectorInput } from '../../model/availableVariables.js'
import { useAvailableVariables } from '../../model/useAvailableVariables.js'
import {
  addIfElseCase,
  createIfElseCondition,
  getIfElseOperators,
  isIfElseOperatorValueRequired,
  normalizeIfElseData,
  removeIfElseCase,
  resolveIfElseVariable,
} from './ifElseNode.js'

/**
 * 比较运算符全量选项配置表
 * 对应 Dify 原生支持的文本、数字、布尔等条件比较类型
 */
export const COMPARISON_OPERATORS = getIfElseOperators('string')

/**
 * IF/ELSE 逻辑条件分支节点的配置状态与逻辑 Composable
 * 负责管理控制分支集合 (cases)、分支锚点引用 (_targetBranches) 及条件逻辑判定
 *
 * @param {Object} props - 组件传入的属性对象
 * @param {Function} emit - 事件触发回调
 */
export function useIfElseConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  // 是否只读
  const readOnly = computed(() => props.readOnly || false)
  const { availableVarGroups } = useAvailableVariables(() => props.nodeId)

  // 计算并提供默认分支 Handle 列表 (如 IF / ELSE / ELIF 1)
  const targetBranches = computed(() => {
    return normalizeIfElseData(nodeData.value)._targetBranches
  })

  // 条件组集合 (cases)
  const cases = computed(() => {
    return normalizeIfElseData(nodeData.value).cases
  })

  /**
   * 状态变更后统一触发父层 update:nodeData 通知
   */
  const emitUpdate = (newCases) => {
    const next = normalizeIfElseData({
      ...nodeData.value,
      cases: newCases || cases.value,
    })
    emit('update:nodeData', next)
  }

  /**
   * 修改指定条件组的逻辑关系运算符 (AND / OR)
   * @param {Number} caseIndex - 条件组索引
   * @param {String} operator - 'and' | 'or'
   */
  const handleUpdateLogicalOperator = (caseIndex, operator) => {
    const nextCases = JSON.parse(JSON.stringify(cases.value))
    if (nextCases[caseIndex]) {
      nextCases[caseIndex].logical_operator = operator
      emitUpdate(nextCases)
    }
  }

  /**
   * 向指定条件组追加一条新的条件比较规则
   * @param {Number} caseIndex - 条件组索引
   */
  const handleAddCondition = (caseIndex) => {
    const nextCases = JSON.parse(JSON.stringify(cases.value))
    if (nextCases[caseIndex]) {
      nextCases[caseIndex].conditions.push({
        ...createIfElseCondition(),
      })
      emitUpdate(nextCases)
    }
  }

  /**
   * 删除条件组内的指定规则条目
   * @param {Number} caseIndex - 条件组索引
   * @param {Number} condIndex - 规则条目索引
   */
  const handleRemoveCondition = (caseIndex, condIndex) => {
    const nextCases = JSON.parse(JSON.stringify(cases.value))
    if (nextCases[caseIndex]) {
      nextCases[caseIndex].conditions.splice(condIndex, 1)
      emitUpdate(nextCases)
    }
  }

  /**
   * 更新具体条件规则的字段 (选择器路径, 比较符, 比较值)
   */
  const handleUpdateCondition = (caseIndex, condIndex, key, val) => {
    const nextCases = JSON.parse(JSON.stringify(cases.value))
    if (nextCases[caseIndex] && nextCases[caseIndex].conditions[condIndex]) {
      if (key === 'variable_selector') {
        nextCases[caseIndex].conditions[condIndex].variable_selector = parseSelectorInput(val)
      } else {
        nextCases[caseIndex].conditions[condIndex][key] = val
        if (key === 'comparison_operator' && !isIfElseOperatorValueRequired(val))
          nextCases[caseIndex].conditions[condIndex].value = ''
      }
      emitUpdate(nextCases)
    }
  }

  /**
   * 添加一个 ELIF (否则如果) 分支条件
   */
  const handleAddElifCase = () => {
    emit('update:nodeData', addIfElseCase({ ...nodeData.value, cases: cases.value }))
  }

  /**
   * 删除指定的 ELIF 分支
   * @param {Number} caseIndex - 要删除的 case 下标 (第一项 IF 不可删除)
   */
  const handleRemoveElifCase = (caseId) => {
    const next = removeIfElseCase({ ...nodeData.value, cases: cases.value }, caseId)
    if (next.cases.length === cases.value.length) return
    emit('update:nodeData', next)
  }

  const operatorsForCondition = condition => getIfElseOperators(
    condition?.varType,
    condition?.key ? { key: condition.key } : undefined,
  )

  const handleSelectVariable = (caseIndex, condIndex, selector) => {
    const parsed = parseSelectorInput(selector)
    const variable = resolveIfElseVariable(availableVarGroups.value, parsed)
    const nextCases = JSON.parse(JSON.stringify(cases.value))
    const condition = nextCases[caseIndex]?.conditions?.[condIndex]
    if (!condition) return
    const replacement = variable
      ? createIfElseCondition({ variableSelector: parsed, varType: variable.type, file: variable.file })
      : createIfElseCondition({ variableSelector: parsed, varType: '' })
    replacement.id = condition.id || replacement.id
    Object.assign(condition, replacement)
    if (!variable) {
      condition.comparison_operator = ''
      condition.value = ''
    }
    if (!replacement.key)
      delete condition.key
    delete condition.sub_variable_condition
    emitUpdate(nextCases)
  }

  return {
    readOnly,
    targetBranches,
    cases,
    COMPARISON_OPERATORS,
    handleUpdateLogicalOperator,
    handleAddCondition,
    handleRemoveCondition,
    handleUpdateCondition,
    handleSelectVariable,
    operatorsForCondition,
    handleAddElifCase,
    handleRemoveElifCase
  }
}
