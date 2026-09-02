import test from 'node:test'
import assert from 'node:assert/strict'

import * as assistLiveAnnouncement from './assistLiveAnnouncement.js'

const { createAssistLiveAnnouncement } = assistLiveAnnouncement

test('streaming deltas coalesce into one screen-reader announcement', () => {
  const timers = []
  const announcements = []
  const live = createAssistLiveAnnouncement({
    delay: 250,
    setTimeoutImpl(fn, delay) {
      const timer = { active: true, fn, delay }
      timers.push(timer)
      return timer
    },
    clearTimeoutImpl(timer) {
      timer.active = false
    },
    onAnnounce: text => announcements.push(text),
  })

  live.update('Hel')
  live.update('Hello')
  live.update('Hello world')

  assert.equal(timers.filter(timer => timer.active).length, 1)
  assert.equal(timers.at(-1).delay, 250)
  timers.at(-1).fn()
  assert.deepEqual(announcements, ['Hello world'])
})

test('detaching clears a pending screen-reader announcement', () => {
  const timers = []
  const announcements = []
  const live = createAssistLiveAnnouncement({
    setTimeoutImpl(fn) {
      const timer = { active: true, fn }
      timers.push(timer)
      return timer
    },
    clearTimeoutImpl(timer) { timer.active = false },
    onAnnounce: text => announcements.push(text),
  })

  live.update('partial')
  live.dispose()
  assert.equal(timers[0].active, false)
  assert.deepEqual(announcements, [])
})

test('terminal transition flushes the pending aggregate exactly once', () => {
  const timers = []
  const announcements = []
  const live = createAssistLiveAnnouncement({
    setTimeoutImpl(fn) {
      const timer = { active: true, fn }
      timers.push(timer)
      return timer
    },
    clearTimeoutImpl(timer) { timer.active = false },
    onAnnounce: text => announcements.push(text),
  })

  live.update('Complete answer')
  live.update('')

  assert.equal(timers[0].active, false)
  assert.deepEqual(announcements, ['Complete answer'])
  timers[0].fn()
  assert.deepEqual(announcements, ['Complete answer'])
})

test('meaningful Run and Apply transitions announce once per actual channel transition', () => {
  const { createAssistStatusAnnouncement } = assistLiveAnnouncement
  assert.equal(typeof createAssistStatusAnnouncement, 'function')
  const announcements = []
  const live = createAssistStatusAnnouncement({
    onAnnounce: text => announcements.push(text),
  })

  live.update('run', 'queued', 'Run queued')
  live.update('run', 'queued', 'Run queued')
  live.update('run', 'running', 'Run running')
  live.update('run', 'running', 'Run running')
  live.update('run', 'waiting_user', 'Run needs an answer')
  live.update('run', 'done', 'Run done')
  live.update('run', 'done', 'Run done')
  live.update('apply', 'applying', 'Applying changes')
  live.update('apply', 'applying', 'Applying changes')
  live.update('apply', 'applied', 'Changes applied')
  live.update('run', 'queued', 'Run queued')

  assert.deepEqual(announcements, [
    'Run queued',
    'Run running',
    'Run needs an answer',
    'Run done',
    'Applying changes',
    'Changes applied',
    'Run queued',
  ])
})

test('all required terminal Run states remain independently announceable', () => {
  const { createAssistStatusAnnouncement } = assistLiveAnnouncement
  assert.equal(typeof createAssistStatusAnnouncement, 'function')
  const announcements = []
  const live = createAssistStatusAnnouncement({
    onAnnounce: text => announcements.push(text),
  })

  live.update('run', 'failed', 'Run failed')
  live.update('run', 'error', 'Run error')
  live.update('run', 'aborted', 'Run stopped')
  live.update('apply', 'conflict', 'Apply conflict')
  live.update('apply', 'failed', 'Apply failed')

  assert.deepEqual(announcements, [
    'Run failed',
    'Run error',
    'Run stopped',
    'Apply conflict',
    'Apply failed',
  ])
})
