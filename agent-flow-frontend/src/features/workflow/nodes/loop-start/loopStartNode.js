import { BlockEnum } from '../../model/constants.js'

export const LOOP_START_DEFAULTS = Object.freeze({
  title: '',
  desc: '',
  isInLoop: true,
})

export function normalizeLoopStartData(data = {}) {
  return {
    ...LOOP_START_DEFAULTS,
    ...data,
    type: BlockEnum.LoopStart,
    title: '',
    desc: '',
    isInLoop: true,
  }
}
