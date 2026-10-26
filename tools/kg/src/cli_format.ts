/**
 * CLI 输出格式化（`kg:ask` 共用）。
 *
 * 为什么单独抽一个模块：`kg_ask.ts` 是脚本，顶层就读 argv 并执行，无法被单测 import。
 * 把纯格式化逻辑拆出来，才能对「页码怎么拼」「没有页码时会不会留尾随制表符」做断言。
 */
import type { Entity } from './schema/types.js'

/**
 * 页码后缀：实体带 `pageRange` 时输出 `\tp.起-止`，否则空串。
 *
 * 2026-10-26：此前 `kg:ask covered` 只打 id/标题/类型，agent 拿不到页码，
 * 回答「教材第几页」只能靠猜。而 2,976 个节全部有 pageRange，数据本来就在。
 */
export function pageSuffix(e: Entity): string {
  const pr = (e as { pageRange?: unknown }).pageRange
  if (!Array.isArray(pr) || pr.length !== 2) return ''
  const [from, to] = pr as [unknown, unknown]
  if (from === undefined || to === undefined) return ''
  return `\tp.${from}-${to}`
}

/** 每实体一行：`id \t 标题 \t [类型] \t p.起-止` */
export function formatLine(e: Entity, title: (x: Entity) => string): string {
  return `${e.id}\t${title(e)}\t[${e.type ?? ''}]${pageSuffix(e)}`
}
