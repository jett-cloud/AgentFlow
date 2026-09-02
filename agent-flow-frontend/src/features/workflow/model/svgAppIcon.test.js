import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  calculateSquareCrop,
  sanitizeSvgMarkup,
  validateAppIconFile,
} from './svgAppIcon.js'

test('sanitizeSvgMarkup accepts a self-contained SVG icon', () => {
  const result = sanitizeSvgMarkup(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
      <path fill="#2563eb" d="M4 4h16v16H4z" />
    </svg>
  `)

  assert.match(result, /^<svg/)
  assert.match(result, /viewBox="0 0 24 24"/)
})

test('sanitizeSvgMarkup rejects executable or externally loaded SVG content', () => {
  for (const markup of [
    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><path onclick="alert(1)" /></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/a.png" /></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject /></svg>',
  ])
    assert.throws(() => sanitizeSvgMarkup(markup), /安全|SVG/)
})

test('validateAppIconFile accepts supported still image formats and rejects GIF', () => {
  for (const type of ['image/png', 'image/jpeg', 'image/webp', 'image/svg+xml'])
    assert.doesNotThrow(() => validateAppIconFile({ type, size: 1024 }))

  assert.throws(() => validateAppIconFile({ type: 'image/gif', size: 1024 }), /PNG|JPG|WebP|SVG/)
  assert.throws(() => validateAppIconFile({ type: 'image/png', size: 6 * 1024 * 1024 }), /5 MB/)
})

test('calculateSquareCrop maps the visible square back to source pixels', () => {
  assert.deepEqual(
    calculateSquareCrop({ width: 800, height: 400, frameSize: 300, zoom: 1, offsetX: 0, offsetY: 0 }),
    { sx: 200, sy: 0, size: 400 },
  )
  assert.deepEqual(
    calculateSquareCrop({ width: 800, height: 400, frameSize: 300, zoom: 2, offsetX: 75, offsetY: 0 }),
    { sx: 250, sy: 100, size: 200 },
  )
})

test('create dialog exposes image upload and a square crop dialog', () => {
  const source = readFileSync(new URL('../ui/CreateAppDialog.vue', import.meta.url), 'utf8')
  const cropDialog = readFileSync(new URL('../ui/ImageCropDialog.vue', import.meta.url), 'utf8')

  assert.match(source, /accept="image\/png,image\/jpeg,image\/webp,image\/svg\+xml,\.svg"/)
  assert.match(source, /uploadConsoleFile/)
  assert.match(source, /icon_type:\s*iconSelection\.value\.type/)
  assert.match(source, /<ImageCropDialog/)
  assert.match(cropDialog, /type="range"/)
  assert.match(cropDialog, /pointermove/)
})
