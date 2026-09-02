// src/views/copilot/components/workflow/node/iteration/useIterationConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import { parseSelectorInput } from '../../model/availableVariables.js'

export function useIterationConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)

  // 1. 待迭代的数组变量选择器 (iterator_selector)
  const iteratorSelector = computed({
    get: () => nodeData.value?.iterator_selector || ['start', 'files'],
    set: (val) => {
      const sel = parseSelectorInput(val)
      emit('update:nodeData', { ...nodeData.value, iterator_selector: sel })
    }
  })

  // 2. 并行运行模式开关 (is_parallel)
  const isParallel = computed({
    get: () => nodeData.value?.is_parallel || false,
    set: (val) => emit('update:nodeData', { ...nodeData.value, is_parallel: val })
  })

  // 3. 最大并发数限制 (parallel_nums)
  const parallelNums = computed({
    get: () => nodeData.value?.parallel_nums || 10,
    set: (val) => emit('update:nodeData', { ...nodeData.value, parallel_nums: val })
  })

  // 4. 对齐 Dify DSL 的 error_handle_mode
  const errorStrategy = computed({
    get: () => nodeData.value?.error_handle_mode || nodeData.value?.error_strategy || 'terminated',
    set: (val) => emit('update:nodeData', {
      ...nodeData.value,
      error_handle_mode: val,
      error_strategy: undefined,
    })
  })

  return {
    readOnly,
    iteratorSelector,
    isParallel,
    parallelNums,
    errorStrategy
  }
}
