import test from 'node:test'
import assert from 'node:assert/strict'

import { getContainerFitSize } from './containerLayout.js'

test('container fit uses measured child content instead of stale persisted height', () => {
  const size = getContainerFitSize({
    currentWidth: 640,
    currentHeight: 200,
    children: [{
      position: { x: 160, y: 68 },
      dimensions: { width: 240, height: 172 },
      width: 244,
      height: 100,
    }],
  })

  assert.deepEqual(size, { width: 640, height: 264 })
})

test('container expands when a connected child is added beyond its right edge', () => {
  const size = getContainerFitSize({
    currentWidth: 1548,
    currentHeight: 204,
    children: [{
      position: { x: 1530, y: 68 },
      dimensions: { width: 240, height: 100 },
    }],
  })

  assert.deepEqual(size, { width: 1794, height: 204 })
})
