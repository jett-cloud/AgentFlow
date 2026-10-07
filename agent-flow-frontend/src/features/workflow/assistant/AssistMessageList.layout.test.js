import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { chromium } from 'playwright'

const componentSource = readFileSync(new URL('./AssistMessageList.vue', import.meta.url), 'utf8')
const componentStyles = componentSource
  .match(/<style scoped>([\s\S]*?)<\/style>/)?.[1]
  .replaceAll(':deep(', ':is(')

async function launchBrowser(t) {
  try {
    return await chromium.launch({ headless: true })
  }
  catch {
    try {
      return await chromium.launch({ channel: 'chrome', headless: true })
    }
    catch {
      t.skip('No Chromium browser is available for the layout regression test')
      return null
    }
  }
}

test('long code scrolls inside its block without making the message list scroll sideways', async (t) => {
  assert.ok(componentStyles)
  const browser = await launchBrowser(t)
  if (!browser)
    return

  t.after(() => browser.close())
  const page = await browser.newPage()
  const longCode = 'start -> retrieve -> generate -> parse -> iterate -> judge -> aggregate -> end '.repeat(8)

  await page.setContent(`
    <style>${componentStyles}</style>
    <div style="display: flex; width: 560px; height: 400px">
      <div class="assist-message-list">
        <article class="message">
          <div class="bubble turn markdown-body">
            <div class="turn-text">
              <pre class="markdown-code-block">${longCode}</pre>
            </div>
          </div>
        </article>
      </div>
    </div>
  `)

  const layout = await page.locator('.assist-message-list').evaluate((list) => {
    const code = list.querySelector('.markdown-code-block')
    return {
      listClientWidth: list.clientWidth,
      listScrollWidth: list.scrollWidth,
      listOverflowX: getComputedStyle(list).overflowX,
      codeClientWidth: code.clientWidth,
      codeScrollWidth: code.scrollWidth,
      codeOverflowX: getComputedStyle(code).overflowX,
    }
  })

  assert.equal(layout.listOverflowX, 'hidden')
  assert.equal(layout.listScrollWidth, layout.listClientWidth)
  assert.equal(layout.codeOverflowX, 'auto')
  assert.ok(layout.codeScrollWidth > layout.codeClientWidth)
})

test('assistant turn keeps the same width while streaming content grows', async (t) => {
  assert.ok(componentStyles)
  const browser = await launchBrowser(t)
  if (!browser)
    return

  t.after(() => browser.close())
  const page = await browser.newPage()

  await page.setContent(`
    <style>${componentStyles}</style>
    <div style="display: flex; width: 560px; height: 400px">
      <div class="assist-message-list">
        <article class="message is-assistant">
          <div class="bubble turn"><div class="turn-text">思考中</div></div>
        </article>
      </div>
    </div>
  `)

  const shortWidth = await page.locator('.message.is-assistant').evaluate(el => el.getBoundingClientRect().width)
  const shortBubbleWidth = await page.locator('.message.is-assistant > .bubble').evaluate(el => el.getBoundingClientRect().width)
  await page.locator('.turn-text').evaluate((el) => {
    el.textContent = '正在持续生成工作流内容。'.repeat(40)
  })
  const longWidth = await page.locator('.message.is-assistant').evaluate(el => el.getBoundingClientRect().width)
  const longBubbleWidth = await page.locator('.message.is-assistant > .bubble').evaluate(el => el.getBoundingClientRect().width)

  assert.ok(shortWidth > 400)
  assert.equal(longWidth, shortWidth)
  assert.equal(shortBubbleWidth, shortWidth)
  assert.equal(longBubbleWidth, shortBubbleWidth)
})

test('long raw errors wrap and scroll inside the error card', async (t) => {
  assert.ok(componentStyles)
  const browser = await launchBrowser(t)
  if (!browser)
    return

  t.after(() => browser.close())
  const page = await browser.newPage()
  const longToken = 'PluginInvokeErrorWithoutAnyNaturalBreak'.repeat(18)
  const traceback = Array.from({ length: 30 }, (_, index) => `${index}: ${longToken}`).join('\n')

  await page.setContent(`
    <style>${componentStyles}</style>
    <div style="display: flex; width: 420px; height: 500px">
      <div class="assist-message-list">
        <section class="error-list">
          <details class="error-details" open>
            <summary>查看原始错误</summary>
            <pre class="error-detail">${traceback}</pre>
          </details>
        </section>
      </div>
    </div>
  `)

  const layout = await page.locator('.error-detail').evaluate((detail) => {
    const list = detail.closest('.assist-message-list')
    const styles = getComputedStyle(detail)
    return {
      listClientWidth: list.clientWidth,
      listScrollWidth: list.scrollWidth,
      detailClientHeight: detail.clientHeight,
      detailScrollHeight: detail.scrollHeight,
      overflowY: styles.overflowY,
      overflowWrap: styles.overflowWrap,
      whiteSpace: styles.whiteSpace,
    }
  })

  assert.equal(layout.listScrollWidth, layout.listClientWidth)
  assert.equal(layout.overflowY, 'auto')
  assert.equal(layout.overflowWrap, 'anywhere')
  assert.equal(layout.whiteSpace, 'pre-wrap')
  assert.ok(layout.detailScrollHeight > layout.detailClientHeight)
})
