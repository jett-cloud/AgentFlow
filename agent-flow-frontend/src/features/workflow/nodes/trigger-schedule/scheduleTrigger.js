/**
 * Schedule trigger visual → cron helpers.
 * Contrasts Dify trigger-schedule visual_config + frequency.
 */

export const SCHEDULE_FREQUENCIES = ['hourly', 'daily', 'weekly', 'monthly']

export function getDefaultVisualConfig() {
  return {
    time: '09:00',
    on_minute: 0,
    weekdays: ['1'],
    monthly_days: [1],
  }
}

/**
 * Build a cron expression from visual schedule fields.
 * Cron format: minute hour day-of-month month day-of-week
 * @param {{ frequency?: string, visual_config?: object }} input
 */
export function buildCronFromVisual({ frequency = 'daily', visual_config = {} } = {}) {
  const config = { ...getDefaultVisualConfig(), ...visual_config }
  const minute = clampInt(config.on_minute, 0, 59)
  const [hourRaw, minuteFromTime] = String(config.time || '09:00').split(':')
  const hour = clampInt(hourRaw, 0, 23)
  const timeMinute = clampInt(minuteFromTime, 0, 59)

  if (frequency === 'hourly')
    return `${minute} * * * *`

  if (frequency === 'weekly') {
    const days = (Array.isArray(config.weekdays) && config.weekdays.length)
      ? config.weekdays.map(String).join(',')
      : '1'
    return `${timeMinute} ${hour} * * ${days}`
  }

  if (frequency === 'monthly') {
    const days = (Array.isArray(config.monthly_days) && config.monthly_days.length)
      ? config.monthly_days.map(Number).filter(n => n >= 1 && n <= 31).join(',')
      : '1'
    return `${timeMinute} ${hour} ${days || 1} * *`
  }

  // daily
  return `${timeMinute} ${hour} * * *`
}

/**
 * Resolve effective cron for node data (cron mode or visual).
 * @param {object} nodeData
 */
export function resolveScheduleCron(nodeData = {}) {
  const mode = nodeData.mode || (nodeData.cron || nodeData.cron_expression ? 'cron' : 'visual')
  if (mode === 'cron')
    return String(nodeData.cron || nodeData.cron_expression || '').trim()
  return buildCronFromVisual({
    frequency: nodeData.frequency || 'daily',
    visual_config: nodeData.visual_config,
  })
}

function clampInt(value, min, max) {
  const n = Number.parseInt(String(value ?? ''), 10)
  if (!Number.isFinite(n))
    return min
  return Math.min(max, Math.max(min, n))
}
