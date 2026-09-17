// src/views/copilot/components/workflow/node/question-classifier/useQuestionClassifierConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { normalizeQuestionClassifierData } from './questionClassifierNode.js'

export function useQuestionClassifierConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)

  const classes = computed(() => {
    return normalizeQuestionClassifierData(nodeData.value).classes
  })

  const targetBranches = computed(() => {
    return classes.value.map((c) => ({
      id: c.id,
      name: c.name
    }))
  })

  const emitUpdate = (newClasses) => {
    const newBranches = newClasses.map((c) => ({ id: c.id, name: c.name }))
    emit('update:nodeData', {
      ...normalizeQuestionClassifierData(nodeData.value),
      classes: newClasses,
      _targetBranches: newBranches
    })
  }

  const handleAddClass = (className) => {
    const list = [...classes.value]
    const newId = `class_${Date.now()}`
    list.push({ id: newId, name: className || '', label: `CLASS ${list.length + 1}` })
    emitUpdate(list)
  }

  const handleRemoveClass = (index) => {
    if (classes.value.length <= 2) return
    const list = [...classes.value]
    list.splice(index, 1)
    emitUpdate(list)
  }

  const handleUpdateClassName = (index, newName) => {
    const list = JSON.parse(JSON.stringify(classes.value))
    if (list[index]) {
      list[index].name = newName
      emitUpdate(list)
    }
  }

  return {
    readOnly,
    classes,
    targetBranches,
    handleAddClass,
    handleRemoveClass,
    handleUpdateClassName
  }
}
