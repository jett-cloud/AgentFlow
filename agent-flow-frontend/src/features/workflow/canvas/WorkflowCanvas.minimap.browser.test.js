import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { createServer } from 'node:http'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { chromium } from 'playwright'
import { createServer as createViteServer } from 'vite'

const projectRoot = fileURLToPath(new URL('../../../..', import.meta.url))

test('workflow minimap renders its SVG and nodes inside the visible panel', async t => {
  const vite = await createViteServer({
    configFile: false,
    root: projectRoot,
    appType: 'custom',
    plugins: [vue()],
    resolve: { alias: { '@': `${projectRoot}/src` } },
    server: { middlewareMode: true, hmr: false },
  })
  const server = createServer((request, response) => {
    if (request.url === '/favicon.ico') {
      response.writeHead(204)
      response.end()
      return
    }
    if (request.url === '/' || request.url === '/index.html') {
      vite.transformIndexHtml('/', `<!doctype html>
        <html>
          <body style="margin:0">
            <div id="app"></div>
            <script type="module" src="/src/features/workflow/canvas/__fixtures__/workflowCanvasMiniMapBrowserFixture.js"></script>
          </body>
        </html>`).then(html => {
        response.writeHead(200, { 'Content-Type': 'text/html' })
        response.end(html)
      })
      return
    }
    vite.middlewares(request, response, () => {
      response.statusCode = 404
      response.end('not found')
    })
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))

  let browser
  t.after(async () => {
    await browser?.close()
    await new Promise(resolve => server.close(resolve))
    await vite.close()
  })
  const bundledChromium = chromium.executablePath()
  browser = await chromium.launch({
    ...(existsSync(bundledChromium) ? { executablePath: bundledChromium } : { channel: 'chrome' }),
    headless: true,
  })

  const address = server.address()
  const page = await browser.newPage()
  const browserErrors = []
  page.on('console', message => {
    if (message.type() === 'error')
      browserErrors.push(message.text())
  })
  page.on('pageerror', error => browserErrors.push(error.message))
  await page.goto(`http://127.0.0.1:${address.port}/`)

  const minimap = page.locator('.vue-flow__minimap')
  const node = minimap.locator('.vue-flow__minimap-node')
  await node.waitFor()

  const layout = await minimap.evaluate(element => {
    const svg = element.querySelector('svg')
    const node = element.querySelector('.vue-flow__minimap-node')
    const nodeRect = node.getBoundingClientRect()
    const panelRect = element.getBoundingClientRect()
    const parseColor = (value) => {
      const channels = value.match(/[\d.]+/g).map(Number)
      return {
        red: channels[0],
        green: channels[1],
        blue: channels[2],
        alpha: channels[3] ?? 1,
      }
    }
    const background = parseColor(getComputedStyle(element).backgroundColor)
    const foreground = parseColor(getComputedStyle(node).fill)
    const blended = ['red', 'green', 'blue'].map(channel => (
      foreground[channel] * foreground.alpha + background[channel] * (1 - foreground.alpha)
    ))
    const luminance = channels => channels
      .map(channel => channel / 255)
      .map(channel => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4)
      .reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0)
    const foregroundLuminance = luminance(blended)
    const backgroundLuminance = luminance([background.red, background.green, background.blue])
    return {
      panelClientWidth: element.clientWidth,
      panelClientHeight: element.clientHeight,
      svgClientWidth: svg.clientWidth,
      svgClientHeight: svg.clientHeight,
      nodeInsidePanel: nodeRect.left >= panelRect.left
        && nodeRect.top >= panelRect.top
        && nodeRect.right <= panelRect.right
        && nodeRect.bottom <= panelRect.bottom,
      nodeContrast: (Math.max(foregroundLuminance, backgroundLuminance) + 0.05)
        / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05),
    }
  })

  assert.equal(layout.svgClientWidth, layout.panelClientWidth)
  assert.equal(layout.svgClientHeight, layout.panelClientHeight)
  assert.equal(layout.nodeInsidePanel, true)
  assert.ok(layout.nodeContrast >= 3, `expected minimap node contrast >= 3, received ${layout.nodeContrast}`)
  assert.deepEqual(browserErrors, [])
})
