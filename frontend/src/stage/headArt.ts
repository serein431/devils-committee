import type { Role } from '../sse/contract'

// 使用 dicebear personas 风格的 3D 卡通头像
// idle = 闭嘴/中性(待命必显)
// talk = 张嘴/有手势(发言时与 idle 交替,营造"在说话")
export interface HeadArt {
  idle: string
  talk?: string
}

export const HEAD_ART: Partial<Record<Role, HeadArt>> = {
  bull: { idle: '/heads/bull-idle.png', talk: '/heads/bull-talk.png' },
  bear: { idle: '/heads/bear-idle.png', talk: '/heads/bear-talk.png' },
  macro: { idle: '/heads/macro-idle.png', talk: '/heads/macro-talk.png' },
  risk: { idle: '/heads/risk-idle.png', talk: '/heads/risk-talk.png' },
  audit: { idle: '/heads/audit-idle.png', talk: '/heads/audit-talk.png' },
  chair: { idle: '/heads/chair-idle.png', talk: '/heads/chair-talk.png' },
}
