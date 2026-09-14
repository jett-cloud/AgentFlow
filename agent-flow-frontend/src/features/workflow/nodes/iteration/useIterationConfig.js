// src/views/copilot/components/workflow/node/iteration/useIterationConfig.js
import { computed } from 'vue'
import { useResolvedNodeData } from '../../model/nodeProps.js'
import {
  buildIterationInputPatch,
  buildIterationOutputPatch,
  normalizeIterationData,
} from './iterationNode.js'

export function useIterationConfig(props, emit) {
  const nodeData = useResolvedNodeData(props)
  const readOnly = computed(() => props.readOnly || false)
  const normalized = computed(() => normalizeIterationData(nodeData.value))
  const patch = partial => emit('update:nodeData', normalizeIterationData({ ...nodeData.value, ...partial }))

  const iteratorSelector = computed(() => normalized.value.iterator_selector)
  const outputSelector = computed(() => normalized.value.output_selector)
  const outputType = computed(() => normalized.value.output_type)

  const changeIterator = (selector, variable) => patch(buildIterationInputPatch(selector, variable))
  const changeOutput = (selector, variable) => patch(buildIterationOutputPatch(selector, variable))

  const isParallel = computed({
    get: () => normalized.value.is_parallel,
    set: val => patch({ is_parallel: val }),
  })

  const parallelNums = computed({
    get: () => normalized.value.parallel_nums,
    set: val => patch({ parallel_nums: val }),
  })

  const errorStrategy = computed({
    get: () => normalized.value.error_handle_mode,
    set: val => patch({
      error_handle_mode: val,
      error_strategy: undefined,
    }),
  })

  const flattenOutput = computed({
    get: () => normalized.value.flatten_output,
    set: val => patch({ flatten_output: val }),
  })

  return {
    readOnly,
    iteratorSelector,
    outputSelector,
    outputType,
    changeIterator,
    changeOutput,
    isParallel,
    parallelNums,
    errorStrategy,
    flattenOutput,
  }
}
