/* 关系网视图：Canvas 2D + 自写力导向（无第三方依赖）
 *
 * 为什么不用 three.js：
 *   ① 数据是稀疏图（概念度数中位 3，二跳中位 44 节点），3D 只会增加遮挡与操作成本；
 *   ② 要表达的是「谁和谁相连」，不是空间结构，2D 更易读；
 *   ③ three.js 会带进 ~600KB 依赖，而这里 200 节点用 O(n²) 排斥即可 60fps。
 *
 * 坐标系约定（此前踩过坑）：世界坐标 = **CSS 像素**。canvas 的 backing store 按 dpr 放大，
 * 绘制时先 setTransform(dpr,…) 抵消，否则文字与节点只有一半大小（看起来像「缩放不动」）。
 */

const REL = {
  p: { label: '先修', color: '#b0602a' },
  o: { label: '上位', color: '#2f6f4e' },
  r: { label: '相关', color: '#8b8b8b' },
}

function makeNet(canvas, rootId, opts = {}) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return { destroy() {}, stats: { nodes: 0, edges: 0 }, note: '当前环境不支持 canvas' }

  const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1
  const hops = opts.hops ?? 2
  const enabled = new Set(opts.types ?? ['p', 'o', 'r'])
  const MAX = 160
  const adj = opts.adj ?? {}
  const titleOf = opts.titleOf ?? ((x) => x)

  /* ---------- 建图：BFS 两级邻居 ---------- */
  const nodes = new Map()
  const edges = []
  const seenEdge = new Set()
  const push = (id, hop, rel) => {
    if (nodes.size >= MAX || nodes.has(id)) return nodes.has(id)
    nodes.set(id, { id, title: titleOf(id), hop, rel, x: 0, y: 0, vx: 0, vy: 0, fixed: false })
    return true
  }
  push(rootId, 0, null)
  let frontier = [rootId]
  for (let h = 1; h <= hops && frontier.length; h++) {
    const next = []
    for (const id of frontier) {
      for (const [to, rel] of adj[id] ?? []) {
        if (!enabled.has(rel)) continue
        const k = id < to ? `${id}|${to}|${rel}` : `${to}|${id}|${rel}`
        if (!seenEdge.has(k)) {
          seenEdge.add(k)
          if (nodes.has(to) || nodes.size < MAX) edges.push({ a: id, b: to, rel })
        }
        if (!nodes.has(to) && push(to, h, rel)) next.push(to)
      }
    }
    frontier = next
  }
  const kept = edges.filter((e) => nodes.has(e.a) && nodes.has(e.b))

  /* ---------- 尺寸（CSS 像素为准）---------- */
  let vw = 900
  let vh = 600
  const resize = () => {
    const r = canvas.getBoundingClientRect()
    vw = Math.max(320, Math.round(r.width))
    vh = Math.max(260, Math.round(r.height))
    canvas.width = Math.round(vw * dpr)
    canvas.height = Math.round(vh * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    draw()
  }

  /* ---------- 力导向：Fruchterman–Reingold ----------
   * 之前用「斥力 K/(n*0.35) + 固定弹簧」：节点一多斥力被摊薄，弹簧不变，
   * 结果 39 个节点全挤成一团。FR 用理想边长 k=√(面积/n) 归一，
   * 斥力 k²/d、引力 d²/k、位移受温度 temp 限制并退火，规模无关且稳定。
   */
  // k 必须有上下界：纯 √(面积/n) 在节点少时会给出 150+ 的边长，
  // 包络被撑大后 fit 只能缩到 0.4，节点变成 3px 小点（截图反馈）。
  const idealK = () => Math.max(46, Math.min(120, Math.sqrt((vw * vh) / Math.max(1, nodes.size))))

  const init = () => {
    const arr = [...nodes.values()]
    const R = Math.min(vw, vh) * 0.3
    arr.forEach((p, i) => {
      const a = (i / arr.length) * Math.PI * 2 + Math.random() * 0.4
      p.x = vw / 2 + Math.cos(a) * R * (0.6 + Math.random() * 0.6)
      p.y = vh / 2 + Math.sin(a) * R * (0.6 + Math.random() * 0.6)
    })
  }

  const tick = (temp) => {
    const arr = [...nodes.values()]
    const k = idealK()
    const disp = new Map(arr.map((p) => [p.id, { x: 0, y: 0 }]))

    // 斥力：所有点对，f = k²/d
    for (let i = 0; i < arr.length; i++) {
      for (let j = i + 1; j < arr.length; j++) {
        const a = arr[i], b = arr[j]
        let dx = a.x - b.x, dy = a.y - b.y
        let d = Math.hypot(dx, dy)
        if (d < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d = 0.5 }
        const f = (k * k) / d
        const ux = dx / d, uy = dy / d
        disp.get(a.id).x += ux * f; disp.get(a.id).y += uy * f
        disp.get(b.id).x -= ux * f; disp.get(b.id).y -= uy * f
      }
    }

    // 引力：每条边，f = d²/k
    for (const e of kept) {
      const a = nodes.get(e.a), b = nodes.get(e.b)
      const dx = a.x - b.x, dy = a.y - b.y
      const d = Math.hypot(dx, dy) || 0.01
      const f = (d * d) / k
      const ux = dx / d, uy = dy / d
      disp.get(a.id).x -= ux * f; disp.get(a.id).y -= uy * f
      disp.get(b.id).x += ux * f; disp.get(b.id).y += uy * f
    }

    // 位移受温度限制；轻微向心避免孤立分量飘走
    for (const p of arr) {
      if (p.fixed) continue
      const d = disp.get(p.id)
      d.x += (vw / 2 - p.x) * 0.02
      d.y += (vh / 2 - p.y) * 0.02
      const len = Math.hypot(d.x, d.y) || 0.01
      const step = Math.min(len, temp) / len
      p.x += d.x * step
      p.y += d.y * step
    }
  }

  /* ---------- 视图变换 ---------- */
  let scale = 1
  let tx = 0
  let ty = 0
  const toWorld = (mx, my) => ({ x: (mx - tx) / scale, y: (my - ty) / scale })

  const fit = () => {
    const arr = [...nodes.values()]
    if (!arr.length) return
    const xs = arr.map((p) => p.x), ys = arr.map((p) => p.y)
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const w = Math.max(40, maxX - minX), h = Math.max(40, maxY - minY)
    scale = Math.min(2.2, Math.max(0.35, Math.min((vw - 110) / w, (vh - 110) / h)))
    tx = vw / 2 - ((minX + maxX) / 2) * scale
    ty = vh / 2 - ((minY + maxY) / 2) * scale
    draw()
  }

  const zoomAt = (mx, my, factor) => {
    const before = toWorld(mx, my)
    scale = Math.max(0.2, Math.min(6, scale * factor))
    tx = mx - before.x * scale
    ty = my - before.y * scale
    draw()
  }

  /* ---------- 绘制 ---------- */
  const short = (s, max = 10) => (s.length > max ? `${s.slice(0, max - 1)}…` : s)
  let hoverId = null

  const draw = () => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, vw, vh)
    ctx.translate(tx, ty)
    ctx.scale(scale, scale)

    for (const e of kept) {
      const a = nodes.get(e.a), b = nodes.get(e.b)
      const c = REL[e.rel]?.color ?? '#bbb'
      ctx.strokeStyle = c
      ctx.globalAlpha = e.rel === 'r' ? 0.35 : 0.7
      ctx.lineWidth = (e.rel === 'p' ? 2 : 1.2) / scale
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke()
    }
    ctx.globalAlpha = 1

    for (const p of nodes.values()) {
      const isRoot = p.id === rootId
      const col = isRoot ? '#23211e' : (REL[p.rel]?.color ?? '#8b8b8b')
      // 半径按**屏幕像素**固定（世界半径＝屏幕值/scale）：缩放只改间距、不改节点大小，
      // 否则缩到 0.4 时节点只剩 3px，看着像没有节点。
      const rScreenPx = isRoot ? 10 : p.hop === 1 ? 7 : 4.5
      const r = rScreenPx / scale
      if (isRoot) {                        // 中心加一圈浅色光晕，远处也能一眼找到
        ctx.beginPath(); ctx.arc(p.x, p.y, r + 4 / scale, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(35,33,30,.12)'; ctx.fill()
      }
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
      ctx.fillStyle = col; ctx.fill()
      if (isRoot) { ctx.lineWidth = 2.5 / scale; ctx.strokeStyle = '#fff'; ctx.stroke() }
    }

    // 标签在**屏幕空间**绘制（重置变换），字号固定 12px：
    // 之前在缩放坐标系里画，缩放越大字越大，几个标签就把图盖住了。
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.textAlign = 'center'
    ctx.textBaseline = 'alphabetic'
    const drawn = []                    // 已占用的矩形，用于跳过重叠
    const overlaps = (b) => drawn.some((d) => !(b.x2 < d.x1 || b.x1 > d.x2 || b.y2 < d.y1 || b.y1 > d.y2))

    const order = [...nodes.values()].sort((a, b) => (a.id === rootId ? -1 : b.id === rootId ? 1 : a.hop - b.hop))
    for (const p of order) {
      const isRoot = p.id === rootId
      const show = isRoot || p.hop === 1 || p.id === hoverId || nodes.size <= 30
      if (!show) continue
      const sx = p.x * scale + tx
      const sy = p.y * scale + ty
      const fs = isRoot ? 13 : 12
      const rScreen = (isRoot ? 10 : p.hop === 1 ? 7 : 4.5) * scale   // 节点在屏幕上的半径
      const ly = sy - rScreen - 5                                    // 按半径避让，放大时不糊在圆上
      const text = short(p.title, isRoot ? 12 : 10)
      ctx.font = `${isRoot ? 600 : 400} ${fs}px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
      const w = ctx.measureText(text).width
      const box = { x1: sx - w / 2 - 3, x2: sx + w / 2 + 3, y1: ly - fs, y2: ly + 3 }
      if (!isRoot && overlaps(box)) continue
      drawn.push(box)
      ctx.lineWidth = 3
      ctx.strokeStyle = 'rgba(255,255,255,.92)'
      ctx.strokeText(text, sx, ly)
      ctx.fillStyle = isRoot ? '#111' : '#3a3733'
      ctx.fillText(text, sx, ly)
    }
  }

  const run = (times, cool = true) => {
    let temp = idealK() * 0.12
    for (let i = 0; i < times; i++) {
      tick(temp)
      if (cool) temp *= 0.985
    }
    draw()
  }

  /* ---------- 交互 ---------- */
  let dragNode = null
  let panning = null
  let moved = false

  const pos = (ev) => {
    const r = canvas.getBoundingClientRect()
    return { x: ev.clientX - r.left, y: ev.clientY - r.top }
  }
  const pick = (mx, my) => {
    const p0 = toWorld(mx, my)
    let best = null
    let bd = 20 / scale
    for (const p of nodes.values()) {
      const d = Math.hypot(p.x - p0.x, p.y - p0.y)
      if (d < bd) { bd = d; best = p }
    }
    return best
  }

  canvas.onmousedown = (ev) => {
    const m = pos(ev)
    moved = false
    const p = pick(m.x, m.y)
    if (p) { p.fixed = true; dragNode = p } else { panning = { ...m, tx, ty } }
  }
  canvas.onmousemove = (ev) => {
    const m = pos(ev)
    if (dragNode) {
      const w = toWorld(m.x, m.y)
      dragNode.x = w.x; dragNode.y = w.y
      moved = true
      run(2, false)
      return
    }
    if (panning) {
      tx = panning.tx + (m.x - panning.x)
      ty = panning.ty + (m.y - panning.y)
      moved = true
      draw()
      return
    }
    const p = pick(m.x, m.y)
    if ((p?.id ?? null) !== hoverId) { hoverId = p?.id ?? null; draw() }
  }
  canvas.onmouseup = () => {
    if (dragNode) dragNode.fixed = false
    dragNode = null
    panning = null
  }
  canvas.onmouseleave = () => { dragNode = null; panning = null; hoverId = null; draw() }
  canvas.onclick = (ev) => {
    if (moved) return
    const m = pos(ev)
    const p = pick(m.x, m.y)
    if (p) opts.onPick?.(p.id)
  }
  canvas.onwheel = (ev) => {
    ev.preventDefault()
    const m = pos(ev)
    zoomAt(m.x, m.y, ev.deltaY < 0 ? 1.15 : 0.87)
  }

  // 触屏：双指缩放 + 单指拖动
  let pinch = null
  canvas.addEventListener('touchstart', (ev) => {
    if (ev.touches.length === 2) {
      const [a, b] = ev.touches
      pinch = { d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), scale }
    }
  }, { passive: true })
  canvas.addEventListener('touchmove', (ev) => {
    if (ev.touches.length === 2 && pinch) {
      const [a, b] = ev.touches
      const d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
      const r = canvas.getBoundingClientRect()
      zoomAt(r.width / 2, r.height / 2, (d / pinch.d) * (pinch.scale / scale))
      ev.preventDefault()
    }
  }, { passive: false })
  canvas.addEventListener('touchend', () => { pinch = null }, { passive: true })

  init()
  resize()
  run(320)
  fit()

  return {
    stats: { nodes: nodes.size, edges: kept.length, truncated: nodes.size >= MAX },
    resize,
    fit,
    zoom: (f) => zoomAt(vw / 2, vh / 2, f),
    zoomTo: (s) => zoomAt(vw / 2, vh / 2, s / scale),
    get scale() { return scale },
    // 仅用于测试：导出节点屏幕坐标，便于量化布局质量
    _screen: () => [...nodes.values()].map((p) => ({ x: p.x * scale + tx, y: p.y * scale + ty, hop: p.hop })),
    destroy() {
      canvas.onmousedown = canvas.onmousemove = canvas.onmouseup = canvas.onclick = canvas.onwheel = canvas.onmouseleave = null
    },
    redraw: draw,
  }
}

if (typeof window !== 'undefined') window.makeNet = makeNet
