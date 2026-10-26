/* 树状浏览器：教材 → 章 → 节 → 概念
   数据由 `pnpm kg:demo` 生成到 demo/data/，与 graph/ 同源。
   无框架、无构建：一次加载树（286KB），详情与概念分片按需懒加载。 */

const DATA = 'data/'
const state = {
  tree: [],            // [{i,t,k,p}]
  catalog: {},         // 学科 → 教材[]
  kids: new Map(),     // parentId → [node]
  byId: new Map(),     // id → node
  detail: null,        // 懒加载的节点详情
  concepts: new Map(), // 学科 → 概念数组
  config: {},          // { contentBase, repoWeb }
  matrix: [],          // 学科 × 年级 概念数（首屏热力矩阵）
  adj: null,           // 邻接表（关系网视图懒加载）
  groupBy: 'grade',    // 树的一级分组：grade（默认，贴合教材实物）/ subject
  titles: null,        // id → title（复用搜索索引）
  active: null,
}

const $ = (sel) => document.querySelector(sel)
const el = (tag, cls, text) => {
  const n = document.createElement(tag)
  if (cls) n.className = cls
  if (text != null) n.textContent = text
  return n
}
const esc = (s) => String(s ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))

let searchIdx = null
async function ensureSearchIndex() {
  if (!searchIdx) searchIdx = await j('search.json').catch(() => [])
  return searchIdx
}

async function ensureAdj() {
  if (!state.adj) state.adj = await j('adj.json')
  return state.adj
}

async function j(url) {
  const r = await fetch(DATA + url)
  if (!r.ok) throw new Error(`${url} ${r.status}`)
  return r.json()
}

/* ---------- 启动 ---------- */
async function boot() {
  try {
    const [tree, catalog, config, matrix] = await Promise.all([j('tree.json'), j('catalog.json'), j('config.json').catch(() => ({})), j('matrix.json').catch(() => [])])
    state.matrix = matrix
    state.config = config
    state.tree = tree
    state.catalog = catalog
    for (const n of tree) {
      state.byId.set(n.i, n)
      if (n.p) {
        const arr = state.kids.get(n.p) ?? []
        arr.push(n)
        state.kids.set(n.p, arr)
      }
    }
    $('#stats').textContent = `${Object.keys(catalog).length} 学科 · ${tree.filter(n => n.k === 'b').length} 册 · ${tree.filter(n => n.k === 'c').length} 章 · ${tree.filter(n => n.k === 's').length} 节`
    renderTree()
    renderLanding()
  } catch (e) {
    $('#tree').innerHTML = `<div class="loading">数据加载失败：${esc(e.message)}<br>请先跑 <code>pnpm kg:demo</code>，并用 HTTP 服务打开（不能直接双击）</div>`
  }
}

/* ---------- 树 ---------- */
async function renderTree(filter = '') {
  const box = $('#tree')
  box.innerHTML = ''
  const f = filter.trim().toLowerCase()

  if (f) {
    const box2 = el('div')
    box.append(el('div', 'loading', '搜索中…'))
    const idx = await ensureSearchIndex()
    const cHits = idx.filter(c => (c.t || '').toLowerCase().includes(f)).slice(0, 40)
    const nHits = state.tree.filter(n => (n.t || '').toLowerCase().includes(f)).slice(0, 60)
    box.innerHTML = ''

    if (cHits.length) {
      box.append(el('div', 'loading', `概念 ${cHits.length}`))
      for (const c of cHits) {
        const n = row(c.t, '', true, c.s)
        n.dataset.id = c.i
        n.onclick = () => openConcept(c.i)
        box.append(n)
      }
    }
    if (nHits.length) {
      box.append(el('div', 'loading', `章节/教材 ${nHits.length}`))
      for (const n of nHits) box.append(leafRow(n, true))
    }
    if (!cHits.length && !nHits.length) box.append(el('div', 'loading', '没有匹配'))
    return
  }

  box.append(modeBar())
  renderGroups(box)
}

const CN = '一二三四五六七八九'
const gradeLabel = (g) => `${CN[Number(g) - 1] ?? g}年级`

/** 一级分组：年级 → 学科 → 册；或 学科 → 册 */
function renderGroups(box) {
  const wrap = el('div')
  box.append(wrap)

  const group = (label, children, open) => {
    const g = el('div', 'group')
    const head = row(label, open ? '▾' : '▸', false)
    const kids = el('div', 'children')
    kids.style.display = open ? '' : 'none'
    for (const c of children) kids.append(c)
    head.onclick = () => {
      const hidden = kids.style.display === 'none'
      kids.style.display = hidden ? '' : 'none'
      head.querySelector('.twist').textContent = hidden ? '▾' : '▸'
    }
    g.append(head, kids)
    return g
  }

  if (state.groupBy === 'grade') {
    const grades = new Map()
    for (const [subject, books] of Object.entries(state.catalog)) {
      for (const b of books) {
        const k = String(b.grade)
        const m = grades.get(k) ?? new Map()
        const arr = m.get(subject) ?? []
        arr.push(b)
        m.set(subject, arr)
        grades.set(k, m)
      }
    }
    for (const g of [...grades.keys()].sort((a, b) => Number(a) - Number(b))) {
      const subjects = [...grades.get(g).entries()].sort((a, b) => a[0].localeCompare(b[0], 'zh'))
      const subGroups = subjects.map(([subject, books]) =>
        group(subject, books.map((b) => treeRow(state.byId.get(b.id))), false),
      )
      wrap.append(group(gradeLabel(g), subGroups, g === '1'))
    }
  } else {
    for (const [subject, books] of Object.entries(state.catalog)) {
      wrap.append(group(subject, books.map((b) => treeRow(state.byId.get(b.id))), false))
    }
  }
}

function modeBar() {
  const bar = el('div', 'modebar')
  for (const [key, label] of [['grade', '按年级'], ['subject', '按学科']]) {
    const b = el('button', state.groupBy === key ? 'active' : '', label)
    b.onclick = () => {
      if (state.groupBy === key) return
      state.groupBy = key
      renderTree($('#q').value)
    }
    bar.append(b)
  }
  return bar
}

function row(text, twist, isLeaf, kind) {
  const n = el('div', 'node')
  const t = el('span', 'twist' + (isLeaf ? ' leaf' : ''), twist)
  const l = el('span', 'label', text)
  n.append(t, l)
  if (kind) n.append(el('span', 'kind', kind))
  return n
}

function leafRow(node, withPath) {
  const n = row(node.t, '', true, { b: '册', c: '章', s: '节' }[node.k])
  if (withPath) n.title = pathOf(node.i)
  n.onclick = () => {
    select(node.i)
    const found = document.querySelector(`.tree .node[data-id="${CSS.escape(node.i)}"]`)
    if (found) found.scrollIntoView({ block: 'center' })
  }
  n.dataset.id = node.i
  return n
}

function treeRow(node) {
  if (!node) return el('div')
  const kids = state.kids.get(node.i) ?? []
  const n = row(node.t, kids.length ? '▸' : '', kids.length === 0, { b: '册', c: '章', s: '' }[node.k])
  n.dataset.id = node.i
  n.onclick = (ev) => {
    ev.stopPropagation()
    select(node.i)
    if (!kids.length) return
    const next = n.nextElementSibling
    if (next && next.classList.contains('children')) {
      const hidden = next.style.display === 'none'
      next.style.display = hidden ? '' : 'none'
      n.querySelector('.twist').textContent = hidden ? '▾' : '▸'
      return
    }
    const box = el('div', 'children')
    for (const k of kids) box.append(treeRow(k))
    n.after(box)
    n.querySelector('.twist').textContent = '▾'
  }
  return n
}

function pathOf(id) {
  const parts = []
  let cur = state.byId.get(id)
  while (cur) {
    parts.unshift(cur.t)
    cur = cur.p ? state.byId.get(cur.p) : null
  }
  return parts.join(' / ')
}

/* ---------- 详情 ---------- */
async function select(id) {
  state.active = id
  document.querySelectorAll('.tree .node.active').forEach(n => n.classList.remove('active'))
  const hit = document.querySelector(`.tree .node[data-id="${CSS.escape(id)}"]`)
  if (hit) hit.classList.add('active')

  if (!state.detail) {
    $('#detail').innerHTML = '<div class="loading">加载详情…</div>'
    state.detail = await j('detail.json')
  }
  const d = state.detail[id]
  const box = $('#detail')
  box.innerHTML = ''
  box.append(crumbs(id))

  if (!d) { box.append(el('p', 'muted', '该节点无详情')); return }

  if (d.kind === 'textbook') {
    box.append(title(d.title, `${d.subject} · ${d.grade} 年级 · ${d.term === '1' ? '上册' : '下册'} · ${d.publisher ?? ''} · ${d.totalPages ?? '?'} 页`))
    const chs = (state.kids.get(id) ?? [])
    box.append(card('章（' + chs.length + '）', chips(chs.map(c => [c.t, () => select(c.i)]))))
  } else if (d.kind === 'chapter') {
    box.append(title(d.title, d.pageRange ? `p.${d.pageRange[0]}–${d.pageRange[d.pageRange.length - 1]}` : ''))
    const secs = (state.kids.get(id) ?? [])
    box.append(card('节（' + secs.length + '）', chips(secs.map(s => [s.t, () => select(s.i)]))))
  } else if (d.kind === 'section') {
    box.append(title(d.title, d.pageRange ? `教材 p.${d.pageRange[0]}–${d.pageRange[d.pageRange.length - 1]}` : '无页码'))
    if (d.sourceRef) {
      const btn = el('button', null, '阅读本节原文')
      btn.style.cssText = 'font:inherit;border:1px solid var(--line);background:#fff;border-radius:6px;padding:4px 12px;cursor:pointer'
      const hint = el('p', 'muted small', `源文件：${d.sourceRef}`)
      btn.onclick = () => openSource(d.sourceRef, d.title)
      const w = el('div'); w.append(btn, hint)
      box.append(card('教材原文', w))
    }
    const cs = d.concepts ?? []
    box.append(card(`本节涉及 ${cs.length} 个概念`, cs.length
      ? chips(cs.map(c => [c.title, () => openConcept(c.id)]))
      : el('p', 'muted small', '本节尚未挂概念')))
  } else {
    box.append(conceptCard(d))
  }
}

function title(t, sub) {
  const f = document.createDocumentFragment()
  f.append(el('h2', 'title', t))
  if (sub) f.append(el('div', 'sub', sub))
  return f
}

function card(head, body) {
  const c = el('div', 'card')
  c.append(el('h3', null, head))
  c.append(body)
  return c
}

function chips(pairs) {
  const wrap = el('div', 'chips')
  for (const [text, fn] of pairs) {
    const c = el('span', 'chip', text)
    c.onclick = fn
    wrap.append(c)
  }
  return wrap
}

function crumbs(id) {
  const parts = []
  let cur = state.byId.get(id)
  while (cur) { parts.unshift(cur); cur = cur.p ? state.byId.get(cur.p) : null }
  const bar = $('#crumbs')
  bar.innerHTML = ''
  parts.forEach((p, i) => {
    if (i) bar.append(document.createTextNode(' / '))
    const a = el('a', null, p.t)
    a.onclick = () => select(p.i)
    bar.append(a)
  })
  return el('div')
}

/* ---------- 概念卡 ---------- */
async function openConcept(cid) {
  const subject = guessSubject(cid)
  if (subject && !state.concepts.has(subject)) {
    $('#detail').innerHTML = '<div class="loading">加载概念分片…</div>'
    state.concepts.set(subject, await j(`concepts/${encodeURIComponent(subject)}.json`))
  }
  let found = null
  for (const arr of state.concepts.values()) {
    found = arr.find(c => c.id === cid)
    if (found) break
  }
  if (!found) { state.active = cid; await selectConceptLazy(cid); return }
  state.active = cid
  const box = $('#detail')
  box.innerHTML = ''
  box.append(crumbs(cid))
  box.append(conceptCard(found))
}

function guessSubject(cid) {
  const m = /^concept:([^:]+):/.exec(cid)
  return m ? m[1] : null
}

async function selectConceptLazy(cid) {
  $('#detail').innerHTML = '<div class="loading">未找到该概念，可能需要先跑 pnpm kg:demo</div>'
}

function conceptCard(c) {
  const f = document.createDocumentFragment()
  const head = el('div')
  head.append(title(c.title, [c.subject, c.conceptType].filter(Boolean).join(' · ')))
  const btn = el('button', null, '看关系网 →')
  btn.style.cssText = 'font:inherit;border:1px solid var(--line);background:#fff;border-radius:6px;padding:3px 10px;cursor:pointer;margin:-4px 0 12px'
  btn.onclick = () => renderNetwork(c.id, c.title)
  head.append(btn)
  f.append(head)

  if (c.explanation) f.append(card('释义', el('p', null, c.explanation)))

  if (c.misconceptions?.length) {
    const ul = el('ul', 'list')
    for (const m of c.misconceptions) ul.append(el('li', null, m))
    f.append(card(`常见错误（${c.misconceptions.length}）`, ul))
  }

  if (c.masteryCriteria?.length) {
    const ul = el('ul', 'list')
    for (const m of c.masteryCriteria) ul.append(el('li', null, m))
    f.append(card('怎样算学会了', ul))
  }

  if (c.standards?.length) {
    f.append(card('课标', chips(c.standards.map(s => [s.theme, () => {}]))))
  }

  if (c.prereq?.length) {
    f.append(card(`先修（${c.prereq.length}）`, chips(c.prereq.map(p =>
      [p.strength === 'hard' ? `${p.title} · 必须` : p.title, () => openConcept(p.id)]))))
  }

  if (c.broader?.length) {
    f.append(card('上位', chips(c.broader.map(p => [p.title, () => openConcept(p.id)]))))
  }

  if (c.sections?.length) {
    f.append(card(`在教材里（${c.sections.length} 处）`, chips(c.sections.map(s => [
      `${s.title}${s.pageRange ? ` p.${s.pageRange[0]}–${s.pageRange[s.pageRange.length - 1]}` : ''}`,
      () => select(s.id),
    ]))))
  }

  if (c.related?.length) {
    f.append(card('相关', chips(c.related.map(p => [p.title, () => openConcept(p.id)]))))
  }
  return f
}

/* ---------- 搜索 ---------- */
let timer
$('#q').addEventListener('input', (e) => {
  clearTimeout(timer)
  timer = setTimeout(() => renderTree(e.target.value), 120)
})

boot()

/* ---------- 关系网视图 ---------- */
let netInst = null

async function renderNetwork(cid, titleText) {
  const box = $('#detail')
  box.innerHTML = ''
  box.append(crumbs(cid))

  const [adj] = await Promise.all([ensureAdj(), ensureSearchIndex()])
  if (!state.titles) {
    state.titles = new Map((searchIdx ?? []).map(c => [c.i, c.t]))
  }

  const net = el('div')
  const bar = el('div', 'netbar')
  const back = el('button', null, '← 返回卡片')
  back.onclick = () => openConcept(cid)

  const mkToggle = (key, label, color) => {
    const lb = el('label')
    const cb = document.createElement('input')
    cb.type = 'checkbox'
    cb.checked = true
    cb.onchange = rebuild
    lb.append(cb)
    if (color) {
      const dot = el('span', 'dot')
      dot.style.background = color
      lb.append(dot)
    }
    lb.append(document.createTextNode(label))
    lb.dataset.key = key
    return lb
  }
  const toggles = el('span')
  toggles.style.cssText = 'display:inline-flex;gap:12px'
  toggles.append(
    mkToggle('p', '先修', '#b0602a'),
    mkToggle('o', '上位', '#2f6f4e'),
    mkToggle('r', '相关', '#8b8b8b'),
  )
  const hopSel = el('span', 'netitem')
  const stats = el('span', 'netitem')

  const zoomOut = el('button', null, '−')
  const zoomIn = el('button', null, '+')
  const fitBtn = el('button', null, '适应窗口')
  const scaleTxt = el('span', 'netitem', '100%')
  zoomOut.onclick = () => { netInst?.zoom?.(0.85); syncScale() }
  zoomIn.onclick = () => { netInst?.zoom?.(1.18); syncScale() }
  fitBtn.onclick = () => { netInst?.fit?.(); syncScale() }
  const zoomBox = el('span')
  zoomBox.style.cssText = 'display:inline-flex;gap:6px;align-items:center'
  zoomBox.append(zoomOut, zoomIn, fitBtn, scaleTxt)

  bar.append(back, el('b', null, titleText), toggles, hopSel, zoomBox, stats)
  net.append(bar)

  const canvas = document.createElement('canvas')
  canvas.id = 'net'
  net.append(canvas)
  box.append(net)

  let hops = 2
  const types = () => [...toggles.querySelectorAll('label')].filter(l => l.querySelector('input').checked).map(l => l.dataset.key)
  const hopBtn = el('button', null, '2 跳')
  hopBtn.onclick = () => { hops = hops === 2 ? 1 : 2; hopBtn.textContent = `${hops} 跳`; rebuild() }
  hopSel.append(hopBtn)

  const syncScale = () => { scaleTxt.textContent = `${Math.round((netInst?.scale ?? 1) * 100)}%` }

  function rebuild() {
    netInst?.destroy()
    const r = makeNet(canvas, cid, {
      adj, hops, types: types(),
      titleOf: (id) => state.titles.get(id) ?? id.replace(/^concept:[^:]+:/, ''),
      onPick: (id) => openConcept(id),
    })
    netInst = r
    stats.textContent = `${r.stats?.nodes ?? 0} 节点 / ${r.stats?.edges ?? 0} 边${r.stats?.truncated ? '（已截断到 160）' : ''}`
    syncScale()
  }
  rebuild()
  // 只保留一个 resize 监听：切换概念时先解绑旧的，否则监听器会累积
  window.removeEventListener('resize', onResize)
  function onResize() { netInst?.resize?.() }
  window.addEventListener('resize', onResize, { passive: true })
}

/* ---------- 首屏：学科 × 年级 热力矩阵 ---------- */
const GRADES = [1, 2, 3, 4, 5, 6, 7, 8, 9]

function renderLanding() {
  const box = $('#detail')
  if (!state.matrix.length) return
  const subs = Object.keys(state.catalog)
  const max = Math.max(...state.matrix.map(m => m.concepts))
  const at = (s, g) => state.matrix.find(m => m.subject === s && m.grade === g)?.concepts ?? 0

  const wrap = el('div', 'landing')
  wrap.append(el('h1', null, '一眼看全库：哪个学科、哪个年级最密'))
  wrap.append(el('p', 'lead', '每格是该学科该年级的概念数。点格子跳到对应教材，或直接在上面搜索。'))

  const grid = el('div', 'heat')
  grid.style.gridTemplateColumns = `88px repeat(${GRADES.length}, 1fr)`
  grid.append(el('div', 'hd', ''))
  for (const g of GRADES) grid.append(el('div', 'hd', `${g} 年级`))

  for (const s of subs) {
    grid.append(el('div', 'rowhead', s))
    for (const g of GRADES) {
      const n = at(s, g)
      const c = el('div', 'cell')
      c.textContent = n || ''
      // 面积感知：用 0.55 次幂压缩，避免 553 的大格把其他格压成白色
      const t = n ? Math.pow(n / max, 0.55) : 0
      c.style.background = n ? `rgba(47,111,78,${(0.1 + 0.72 * t).toFixed(3)})` : '#f7f6f3'
      c.style.color = t > 0.55 ? '#fff' : 'var(--text)'
      c.title = `${s} ${g} 年级：${n} 个概念`
      const book = (state.catalog[s] ?? []).find(b => String(b.grade) === String(g))
      if (book) {
        c.classList.add('live')
        c.onclick = () => select(book.id)
      }
      grid.append(c)
    }
  }
  wrap.append(grid)

  const legend = el('div', 'legend')
  legend.append(el('span', null, '少'))
  for (const a of [0.15, 0.35, 0.55, 0.75]) {
    const sw = el('span', 'swatch')
    sw.style.background = `rgba(47,111,78,${a})`
    legend.append(sw)
  }
  legend.append(el('span', null, '多'), el('span', null, `（最多 ${max} 个概念）`))
  wrap.append(legend)

  // 单页示例：用本仓数据生成的零依赖 HTML，用来演示「agent 直接出页面」这条路
  const demoBox = el('div', 'card')
  demoBox.style.marginTop = '22px'
  demoBox.append(el('h3', null, '用本仓数据生成的单页示例'))
  const a = el('a', 'link', '凸透镜成像（教材 p.61–90）→')
  a.href = 'examples/convex-lens.html'
  a.target = '_blank'
  a.rel = 'noreferrer'
  demoBox.append(a, el('p', 'muted small', '单文件、零依赖、双击可开；四步导航 + 滑块调参，页脚挂教材页码与易错点。'))
  wrap.append(demoBox)

  box.innerHTML = ''
  box.append(wrap)
}

/* ---------- 教材原文：面板内渲染 ---------- */
/** 站点根：Pages 部署在 /<repo>/ 下，绝对路径 /content 会跑到域名根去。
 *  以当前页面位置反推：/demo/index.html → /，/faststudy-knowledge/ → /faststudy-knowledge/ */
function siteRoot() {
  const cfg = state.config?.contentBase
  if (cfg && cfg !== '/' && !/^https?:/.test(cfg)) return cfg
  const p = location.pathname
  const dir = p.slice(0, p.lastIndexOf('/') + 1)
  return dir.replace(/demo\/$/, '')
}

async function openSource(sourceRef, titleText) {
  const box = $('#detail')
  const base = siteRoot().replace(/\/$/, '')
  box.innerHTML = '<div class="loading">加载原文…</div>'
  try {
    const r = await fetch(`${base}/${sourceRef}`)
    if (!r.ok) throw new Error(String(r.status))
    const md = await r.text()            // 无 charset 时按 UTF-8 解码，避免中文乱码
    const back = el('button', null, '← 返回')
    back.style.cssText = 'font:inherit;border:1px solid var(--line);background:#fff;border-radius:6px;padding:3px 10px;cursor:pointer;margin-bottom:14px'
    back.onclick = () => select(state.active)
    const art = el('article', 'prose')
    art.innerHTML = window.renderMarkdown ? window.renderMarkdown(md) : `<pre>${md}</pre>`
    box.innerHTML = ''
    box.append(back, el('h2', 'title', titleText || ''), art)
    if (window.typesetMath) window.typesetMath(art)
    box.scrollTop = 0
  } catch (e) {
    box.innerHTML = `<div class="loading">读不到原文：${e.message}<br>请确认从仓库根起服务（python3 -m http.server）</div>`
  }
}
