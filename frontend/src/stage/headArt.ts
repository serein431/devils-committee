import type { Role } from '../sse/contract'

// ⬇️ 唯一需要改的地方:去 peeps.ui8.net 给每个角色捏 3D 头像,导出透明 PNG,
// 放进 frontend/public/heads/,然后在这里填路径。
//   idle = 闭嘴/中性(待命必显)
//   talk = 张嘴/有手势(可选;发言时与 idle 交替,营造"在说话")
// 只填 idle 也行(发言时靠浮动+缩放暗示);两态都填最生动。
// 六个角色全部留空时,自动回退到 CSS 占位球 + emoji。
export interface HeadArt {
  idle: string
  talk?: string
}

export const HEAD_ART: Partial<Record<Role, HeadArt>> = {
  // bull:  { idle: '/heads/bull-idle.png',  talk: '/heads/bull-talk.png' },
  // bear:  { idle: '/heads/bear-idle.png',  talk: '/heads/bear-talk.png' },
  // macro: { idle: '/heads/macro-idle.png', talk: '/heads/macro-talk.png' },
  // risk:  { idle: '/heads/risk-idle.png',  talk: '/heads/risk-talk.png' },
  // audit: { idle: '/heads/audit-idle.png', talk: '/heads/audit-talk.png' },
  // chair: { idle: '/heads/chair-idle.png', talk: '/heads/chair-talk.png' },
}
