import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { chromium } from 'playwright'

const studioSource = readFileSync(new URL('../pages/AiToolPluginStudio.vue', import.meta.url), 'utf8')
const sandboxSource = readFileSync(new URL('./ToolPluginSandbox.vue', import.meta.url), 'utf8')

function componentStyles(source) {
  return [...source.matchAll(/<style(?:\s+scoped)?>([\s\S]*?)<\/style>/g)].map(match => match[1]).join('\n')
}

function browserExecutable() {
  const configured = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
  const candidates = [
    configured,
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  ]
  return candidates.find(candidate => candidate && existsSync(candidate))
}

test('publish dialog keeps outer chrome fixed and scrolls only the parameter panel', async () => {
  const executablePath = browserExecutable()
  const browser = await chromium.launch(executablePath ? { executablePath } : {})
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 } })

  try {
    await page.setContent(`
      <style>
        * { box-sizing: border-box; }
        html, body { height: 100%; margin: 0; }
        .el-overlay-dialog { position: fixed; inset: 0; overflow: auto; }
        .el-dialog { width: 860px; }
        .el-dialog__header { height: 56px; }
        .el-dialog__body { padding: 0; }
        ${componentStyles(studioSource)}
        ${componentStyles(sandboxSource)}
      </style>
      <div class="el-overlay-dialog">
        <div class="el-dialog tool-plugin-publish-dialog">
          <header class="el-dialog__header">发布插件</header>
          <div class="el-dialog__body">
            <section class="sandbox">
              <div class="sandbox-header"><h2>发布插件</h2></div>
              <div class="sandbox-content">
                <div class="node-preview"><div class="tool-node">节点预览</div></div>
                <div class="parameter-panel">
                  <div style="height: 1600px">发布方式与测试参数</div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    `)

    const layout = await page.evaluate(() => {
      const overlay = document.querySelector('.el-overlay-dialog')
      const dialog = document.querySelector('.tool-plugin-publish-dialog')
      const body = document.querySelector('.el-dialog__body')
      const panel = document.querySelector('.parameter-panel')
      return {
        overlayScrolls: overlay.scrollHeight > overlay.clientHeight,
        dialogOverflowY: getComputedStyle(dialog).overflowY,
        bodyOverflowY: getComputedStyle(body).overflowY,
        panelScrolls: panel.scrollHeight > panel.clientHeight,
        panelOverflowY: getComputedStyle(panel).overflowY,
      }
    })

    assert.deepEqual(layout, {
      overlayScrolls: false,
      dialogOverflowY: 'hidden',
      bodyOverflowY: 'hidden',
      panelScrolls: true,
      panelOverflowY: 'auto',
    })
  }
  finally {
    await browser.close()
  }
})
