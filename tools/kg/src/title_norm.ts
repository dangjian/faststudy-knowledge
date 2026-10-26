/** PG↔图谱节标题一致性判定（与下游应用侧同名服务 section-title-agree 保持同语义，跨仓契约；
 * 三档序数剥离共用 tests/fixtures/contract/section-title-agree.vectors.json 契约）。*/
export const normTitle = (t: string) =>
  t
    .replace(/\s+/g, '')
    .replace(/^第[0-9０-９一二三四五六七八九十百]+[节课章]?[、.．:：·]?/, '')
    .replace(/^[0-9０-９]+[、.．:：·]?/, '')
    .replace(/^[一二三四五六七八九十百]+[、.．:：·]/, '')

/** 图谱占位节：「第N节」或空标题——OCR 分块骨架，非真实目录切分 */
export const isPlaceholderTitle = (t: string) => {
  const s = t.trim()
  return s === '' || /^第?[0-9０-９]+节$/.test(s)
}
