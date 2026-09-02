// src/views/copilot/components/workflow/node/if-else/useIfElseConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { parseSelectorInput } from '../../model/availableVariables.js'
import { useAvailableVariables } from '../../model/useAvailableVariables.js'
import { getIfElseOperators, normalizeIfElseData } from './ifElseNode.js'

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
    return nodeData.value?._targetBranches || [
      { id: 'true', name: 'IF' },
      { id: 'false', name: 'ELSE' }
    ]
  })

  // 条件组集合 (cases)
  const cases = computed(() => {
    if (nodeData.value?.cases && nodeData.value.cases.length) {
      return normalizeIfElseData(nodeData.value).cases
    }
    // 默认提供一个 IF 基础条件组
    return [
      {
        case_id: 'true',
        logical_operator: 'and',
        conditions: []
      }
    ]
  })

  /**
   * 状态变更后统一触发父层 update:nodeData 通知
   */
  const emitUpdate = (newCases, newBranches) => {
    const next = normalizeIfElseData({
      ...nodeData.value,
      cases: newCases || cases.value,
      _targetBranches: newBranches || targetBranches.value
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
        id: `condition_${Date.now()}`,
        variable_selector: [],
        varType: 'string',
        comparison_operator: '',
        value: '',
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
    if (nextCases[caseIndex] && nextCases[caseIndex].conditions.length > 1) {
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
      }
      emitUpdate(nextCases)
    }
  }

  /**
   * 添加一个 ELIF (否则如果) 分支条件
   */
  const handleAddElifCase = () => {
    const nextCases = JSON.parse(JSON.stringify(cases.value))
    const nextBranches = JSON.parse(JSON.stringify(targetBranches.value))

    const newCaseId = `case_${Date.now()}`
    const elifCount = nextCases.length

    // 1. 追加到 cases 列表
    nextCases.push({
      case_id: newCaseId,
      logical_operator: 'and',
      conditions: [
        {
          id: `condition_${Date.now()}`,
          variable_selector: [],
          varType: 'string',
          comparison_operator: '',
          value: ''
        }
      ]
    })

    // 2. 将新 ELIF 分支插入到 ELSE 分支之前
    const elseIndex = nextBranches.findIndex((b) => b.id === 'false')
    const newBranch = { id: newCaseId, name: `ELIF ${elifCount}` }

    if (elseIndex !== -1) {
      nextBranches.splice(elseIndex, 0, newBranch)
    } else {
      nextBranches.push(newBranch)
    }

    emitUpdate(nextCases, nextBranches)
  }

  /**
   * 删除指定的 ELIF 分支
   * @param {Number} caseIndex - 要删除的 case 下标 (第一项 IF 不可删除)
   */
  const handleRemoveElifCase = (caseIndex) => {
    if (caseIndex <= 0) return // 主 IF 分支不可删除

    const nextCases = JSON.parse(JSON.stringify(cases.value))
    const nextBranches = JSON.parse(JSON.stringify(targetBranches.value))

    const targetCase = nextCases[caseIndex]
    if (!targetCase) return

    // 1. 从 cases 移除
    nextCases.splice(caseIndex, 1)

    // 2. 从 targetBranches 移除对应 Handle 记录
    const branchIndex = nextBranches.findIndex((b) => b.id === targetCase.case_id)
    if (branchIndex !== -1) {
      nextBranches.splice(branchIndex, 1)
    }

    emitUpdate(nextCases, nextBranches)
  }

  const operatorsForCondition = condition => getIfElseOperators(condition?.varType || 'string')

  const handleSelectVariable = (caseIndex, condIndex, selector) => {
    const parsed = parseSelectorInput(selector)
    const group = availableVarGroups.value.find(item => item.nodeId === parsed[0])
    const variable = group?.vars?.find(item => item.variable === parsed[1])
    const varType = variable?.type || 'string'
    const nextCases = JSON.parse(JSON.stringify(cases.value))
    const condition = nextCases[caseIndex]?.conditions?.[condIndex]
    if (!condition) return
    condition.variable_selector = parsed
    condition.varType = varType
    condition.comparison_operator = getIfElseOperators(varType)[0]?.value || ''
    condition.value = ''
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
