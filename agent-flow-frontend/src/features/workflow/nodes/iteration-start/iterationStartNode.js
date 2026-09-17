import { BlockEnum } from '../../model/constants.js'

export const ITERATION_START_DEFAULTS = Object.freeze({
  title: '',
  desc: '',
  isInIteration: true,
})

export function normalizeIterationStartData(data = {}) {
  return {
    ...ITERATION_START_DEFAULTS,
    ...data,
    type: BlockEnum.IterationStart,
    title: '',
    desc: '',
    isInIteration: true,
  }
}
