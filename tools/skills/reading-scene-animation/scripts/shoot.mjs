/**
 * 逐句截图验收 + 跳读一致性对比
 * 页面契约：#start = 开始按钮；每句可点击元素带 data-cue="<句号>"，文档顺序即句序，第 n 句音频为 n.mp3
 *
 * 截图时刻固定：每句播到 60% 时暂停音频，等镜头稳定（SETTLE_MS）再截，所以两次截图可逐像素比较
 * - 顺播：点 #start 后自然连播，逐句截图 → montage.jpg（加开头待机帧、结束帧）
 * - 跳读：另开一页，从最后一句倒着逐句点 data-cue 跳读，同一时刻截图，与顺播帧逐像素比较
 *   差异大 = 画面状态依赖播放历史（跳读后物体/天色/镜头与顺播不一致），见 consistency.txt / consistency.jpg
 * 截图以 0.5 倍像素比输出，拼图约 1–2MB 以内，可直接读进上下文（原图会撑爆请求上限）
 *
 * 用法：node shoot.mjs <页面 URL> <输出目录>
 * 输出：<输出目录>/montage.jpg（桌面逐句）、mobile.jpg（390×844 手机）、errors.txt（空 = 无报错）、
 *      consistency.txt（每句跳读差异）、consistency.jpg（仅超阈值的句：左顺播 | 右跳读）
 */
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'

const [url, outDir] = process.argv.slice(2)
if (!url || !outDir) {
  console.error('用法：node shoot.mjs <页面 URL> <输出目录>')
  process.exit(1)
}
mkdirSync(outDir, { recursive: true })

const SETTLE_MS = 3500
const FREEZE_AT = 0.6 // 每句音频进度到 60% 时暂停截图
const DIFF_LIMIT = 0.02 // 差异像素占比超过 2% 判为不一致
const browser = await chromium.launch({ args: ['--use-gl=angle', '--autoplay-policy=no-user-gesture-required'] })
const errors = []

async function open(viewport, deviceScaleFactor) {
  const page = await browser.newPage({ viewport, deviceScaleFactor })
  page.on('pageerror', e => errors.push(`PAGEERROR ${e.message}`))
  page.on('requestfailed', r => errors.push(`REQFAIL ${r.url()}`))
  page.on('console', m => { if (m.type() === 'error') errors.push(`CONSOLE ${m.text()}`) })
  // 记下页面正在用的 <audio>，用于定点暂停
  await page.addInitScript(() => {
    const play = HTMLMediaElement.prototype.play
    HTMLMediaElement.prototype.play = function () {
      window.__audio = this
      return play.call(this)
    }
  })
  await page.goto(url)
  await page.waitForTimeout(2000)
  return page
}

const shoot = page => page.screenshot({ type: 'jpeg', quality: 70 })

// 等第 n 句播到 FREEZE_AT → 暂停 → 等镜头稳定 → 截图
async function freezeAt(page, n) {
  await page.waitForFunction(([n, at]) => {
    const a = window.__audio
    return a && decodeURI(a.src).endsWith(`/${n}.mp3`) && a.duration > 0 && a.currentTime >= a.duration * at
  }, [n, FREEZE_AT], { timeout: 30000, polling: 50 })
  await page.evaluate(() => window.__audio.pause())
  await page.waitForTimeout(SETTLE_MS)
  return shoot(page)
}

// 顺播
const page = await open({ width: 1280, height: 760 }, 0.5)
const cues = await page.locator('[data-cue]').evaluateAll(els => els.map(el => Number(el.dataset.cue)))
const idle = await shoot(page)
await page.click('#start')
const seq = []
for (const n of cues) {
  seq.push(await freezeAt(page, n))
  await page.evaluate(() => window.__audio.play())
}
// 最后一句播完 → 结束画面
await page.waitForTimeout(6000)
const end = await shoot(page)

// 倒序跳读
const jumpPage = await open({ width: 1280, height: 760 }, 0.5)
await jumpPage.click('#start')
const jump = []
for (let k = cues.length - 1; k >= 0; k--) {
  await jumpPage.locator('[data-cue]').nth(k).click()
  jump[k] = await freezeAt(jumpPage, cues[k])
}

const grid = await browser.newPage({ viewport: { width: 1920, height: 400 } })
const dataUrl = b => `data:image/jpeg;base64,${b.toString('base64')}`

// 差异像素占比：RGB 平均差 > 40 的像素 / 总像素（JPEG 噪声远小于 40）
const diffs = []
for (let k = 0; k < cues.length; k++) {
  diffs.push(await grid.evaluate(async ([a, b]) => {
    const load = src => new Promise(resolve => { const im = new Image(); im.onload = () => resolve(im); im.src = src })
    const [ia, ib] = await Promise.all([load(a), load(b)])
    const c = document.createElement('canvas')
    c.width = ia.width
    c.height = ia.height
    const ctx = c.getContext('2d')
    ctx.drawImage(ia, 0, 0)
    const da = ctx.getImageData(0, 0, c.width, c.height).data
    ctx.drawImage(ib, 0, 0)
    const db = ctx.getImageData(0, 0, c.width, c.height).data
    let bad = 0
    for (let p = 0; p < da.length; p += 4) {
      if ((Math.abs(da[p] - db[p]) + Math.abs(da[p + 1] - db[p + 1]) + Math.abs(da[p + 2] - db[p + 2])) / 3 > 40) bad++
    }
    return bad / (da.length / 4)
  }, [dataUrl(seq[k]), dataUrl(jump[k])]))
}
const failed = cues.map((n, k) => ({ n, k })).filter(({ k }) => diffs[k] > DIFF_LIMIT)
writeFileSync(`${outDir}/consistency.txt`, [
  `跳读 vs 顺播（第 n 句播到 ${FREEZE_AT * 100}% 暂停、稳定 ${SETTLE_MS}ms 后截图；差异像素占比 > ${DIFF_LIMIT * 100}% 判不一致）`,
  ...cues.map((n, k) => `句 ${n}\t${(diffs[k] * 100).toFixed(2)}%${diffs[k] > DIFF_LIMIT ? '\t✗ 不一致' : ''}`),
].join('\n'))

const montage = async (imgs, cols, path) => {
  await grid.setContent(`<body style="margin:0;display:grid;grid-template-columns:repeat(${cols},640px);background:#000">
    ${imgs.map(b => `<img src="${dataUrl(b)}" width="640" height="380">`).join('')}
  </body>`)
  await grid.screenshot({ path, type: 'jpeg', quality: 60, fullPage: true })
}
await montage([idle, ...seq, end], 3, `${outDir}/montage.jpg`)
rmSync(`${outDir}/consistency.jpg`, { force: true })
if (failed.length) await montage(failed.flatMap(({ k }) => [seq[k], jump[k]]), 2, `${outDir}/consistency.jpg`)

const mobile = await open({ width: 390, height: 844 }, 1)
await mobile.click('#start')
await mobile.locator('[data-cue]').nth(Math.min(3, cues.length - 1)).click()
await mobile.waitForTimeout(SETTLE_MS)
await mobile.screenshot({ path: `${outDir}/mobile.jpg`, type: 'jpeg', quality: 60 })

writeFileSync(`${outDir}/errors.txt`, errors.join('\n'))
console.log(`${seq.length + 2} 帧 → ${outDir}/montage.jpg；报错 ${errors.length} 条；跳读不一致 ${failed.length} 句`)
await browser.close()
