import test from 'node:test'
import assert from 'node:assert/strict'
import { buildToolDetails } from './toolDetails.js'

test('builds expandable tool details from localized API metadata', () => {
  const tools = [
    {
      name: 'generate_image',
      label: { en_US: 'Generate image', zh_Hans: '图片生成' },
      description: { en_US: 'Create an image', zh_Hans: '根据文字描述生成图片' },
    },
    {
      name: 'remove_background',
      label: { zh_Hans: '背景移除' },
      description: '',
    },
  ]

  assert.deepEqual(buildToolDetails(tools), [
    {
      key: 'generate_image:0',
      name: '图片生成',
      description: '根据文字描述生成图片',
    },
    {
      key: 'remove_background:1',
      name: '背景移除',
      description: '暂无详细描述',
    },
  ])
})
