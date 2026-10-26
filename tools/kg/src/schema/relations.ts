import { z } from 'zod'

export const RelationSchema = z.object({
  type: z.enum(['prerequisite', 'related', 'part_of', 'demonstrates', 'covered_by']),
  from: z.string(),
  to: z.string(),
  // 可选元数据：prerequisite 边可标记强度与理由
  strength: z.enum(['hard', 'soft']).optional(),
  reason: z.string().optional(),
  /**
   * prerequisite 边的复核档位。全库先修复核（2026-08） 是唯一做过逐条判定的批次，其后的跨册先修
   * 批次只做过抽样（甚至没有抽样记录），两档精度差一个量级，消费方必须区分。
   * 缺省视为未复核：先修闭包只走 `audited`。
   */
  reviewed: z.enum(['audited', 'sampled']).optional(),
})
