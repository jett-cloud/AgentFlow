import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildCronFromVisual,
  resolveScheduleCron,
} from './scheduleTrigger.js'

test('buildCronFromVisual daily/hourly/weekly/monthly', () => {
  assert.equal(buildCronFromVisual({
    frequency: 'daily',
    visual_config: { time: '09:30' },
  }), '30 9 * * *')

  assert.equal(buildCronFromVisual({
    frequency: 'hourly',
    visual_config: { on_minute: 15 },
  }), '15 * * * *')

  assert.equal(buildCronFromVisual({
    frequency: 'weekly',
    visual_config: { time: '08:00', weekdays: ['1', '5'] },
  }), '0 8 * * 1,5')

  assert.equal(buildCronFromVisual({
    frequency: 'monthly',
    visual_config: { time: '10:00', monthly_days: [1, 15] },
  }), '0 10 1,15 * *')
})

test('resolveScheduleCron prefers cron mode expression', () => {
  assert.equal(resolveScheduleCron({
    mode: 'cron',
    cron: '0 0 * * *',
    frequency: 'daily',
  }), '0 0 * * *')

  assert.equal(resolveScheduleCron({
    mode: 'visual',
    frequency: 'daily',
    visual_config: { time: '09:00' },
  }), '0 9 * * *')
})
