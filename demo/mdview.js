/* 教材原文渲染：fetch .md → 轻量渲染 → 覆盖在详情面板
 *
 * 为什么不直接打开 .md：
 *   ① python -m http.server 给 .md 发 text/markdown 但不带 charset → 中文按错误编码解析成乱码；
 *   ② 即使编码对，浏览器也只显示纯文本，标题/列表/公式全塌。
 * fetch(…).text() 在无 charset 时按 UTF-8 解码，本地自渲染，不依赖外部服务、不引库。
 * 只处理节正文里实际出现的语法：标题、列表、引用、代码、强调、公式、链接、图片、表格。
 */
;(function () {
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))

  const inline = (s) =>
    esc(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g, '<img alt="$1" src="$2" loading="lazy">')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
      .replace(/\$([^$\n]{1,80})\$/g, '<span class="tex">$$$1$$</span>')

  const cells = (line) => line.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())

  // 公式渲染：仅当本节含 $ / $$ 时懒加载 KaTeX（全库 3.8% 的节有公式，首屏零成本）
  let katexLoading = null
  function loadKatex() {
    if (window.katex && window.renderMathInElement) return Promise.resolve()
    if (katexLoading) return katexLoading
    const base = 'vendor/katex/'
    const css = document.createElement('link')
    css.rel = 'stylesheet'
    css.href = base + 'katex.min.css'
    document.head.append(css)
    const load = (src) => new Promise((res, rej) => {
      const s = document.createElement('script')
      s.src = src
      s.onload = res
      s.onerror = () => rej(new Error(src))
      document.head.append(s)
    })
    katexLoading = load(base + 'katex.min.js')
      .then(() => load(base + 'contrib/auto-render.min.js'))
      .catch(() => null)
    return katexLoading
  }

  async function typeset(el) {
    if (!/\$/.test(el.textContent)) return
    await loadKatex()
    if (!window.renderMathInElement) return          // 降级：保留等宽文本
    window.renderMathInElement(el, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
      ],
      throwOnError: false,
    })
  }

  function render(md) {
    const body = md.replace(/^---[\s\S]*?\n---\n?/, '')
    const out = []
    let list = null
    let tbl = null

    const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.join('')}</${list.tag}>`); list = null } }
    const flushTable = () => {
      if (!tbl) return
      out.push(
        `<table><thead><tr>${tbl.head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>` +
        tbl.rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`).join('') +
        '</tbody></table>',
      )
      tbl = null
    }

    for (const raw of body.split('\n')) {
      const line = raw.trimEnd()
      if (!line.trim()) { flushList(); flushTable(); continue }

      const isRow = /^\|.*\|$/.test(line.trim())
      if (isRow) {
        if (/^\|[\s:|-]+\|$/.test(line.trim())) continue          // 分隔行
        if (!tbl) { flushList(); tbl = { head: cells(line.trim()), rows: [] } }
        else tbl.rows.push(cells(line.trim()))
        continue
      }
      flushTable()

      const h = /^(#{1,6})\s+(.*)$/.exec(line)
      if (h) { flushList(); out.push(`<h${Math.min(h[1].length + 1, 6)}>${inline(h[2])}</h${Math.min(h[1].length + 1, 6)}>`); continue }

      const ul = /^[-*+]\s+(.*)$/.exec(line)
      if (ul) {
        if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] } }
        list.items.push(`<li>${inline(ul[1])}</li>`); continue
      }
      const ol = /^\d+[.)]\s+(.*)$/.exec(line)
      if (ol) {
        if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [] } }
        list.items.push(`<li>${inline(ol[1])}</li>`); continue
      }
      if (/^>\s?/.test(line)) { flushList(); out.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`); continue }
      if (/^```/.test(line)) continue                              // 围栏标记交给段落处理，不特殊高亮

      flushList()
      out.push(`<p>${inline(line)}</p>`)
    }
    flushList(); flushTable()
    return out.join('\n')
  }

  window.renderMarkdown = render
  window.typesetMath = typeset
})()
