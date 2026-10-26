// YAML 1.1 布尔保留词字符串回补单引号
// (TS yaml 为 1.2 读回字符串,但 pyyaml 系 YAML 1.1 会读成布尔,写盘约定必须加引号)
import { parse, parseDocument, visit, Scalar } from 'yaml'

const BOOL_WORD = /^(y|yes|no|n|on|off|true|false)$/i

export function requoteBoolWords(src: string): string {
  const doc = parseDocument(src)
  let dirty = false
  visit(doc, {
    Scalar(_key, node) {
      if (typeof node.value === 'string' && BOOL_WORD.test(node.value) && node.type === Scalar.PLAIN) {
        node.type = Scalar.QUOTE_SINGLE
        dirty = true
      }
    },
  })
  if (!dirty) return src
  const out = doc.toString()
  // 自检:修复前后 TS parse 深度相等
  if (JSON.stringify(parse(src)) !== JSON.stringify(parse(out))) {
    throw new Error('requoteBoolWords: 修复前后语义不一致,拒绝输出')
  }
  return out
}
