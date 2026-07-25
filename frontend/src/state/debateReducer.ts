import type {
  Claim,
  DebateEvent,
  DebateResult,
  Role,
  Verdict,
} from '../sse/contract'
import { ROLES, sideOfClaimId } from '../sse/contract'

// 数据层进度(后端事件到哪了)
export type DataPhase =
  | 'standby'
  | 'argue'
  | 'audit'
  | 'synthesize'
  | 'done'
  | 'error'
// 展示层进度(前端回放到哪了)—— 与数据层解耦,由 tick 推进
export type ViewStage = 'standby' | 'arguing' | 'auditing' | 'done'

export type HeadState =
  | 'idle'
  | 'entering'
  | 'speaking'
  | 'waiting'
  | 'flagged'
  | 'audited'

export interface HeadInfo {
  role: Role
  state: HeadState
  confidence?: number
  flagCount: number
}

export interface DebateState {
  dataPhase: DataPhase
  view: ViewStage
  symbol: string | null
  speakerId: Role | null
  heads: Record<Role, HeadInfo>
  claims: Claim[]
  pendingClaims: Claim[] // 待回放队列
  currentClaim: Claim | null
  verdicts: Verdict[]
  result: DebateResult | null
  error: string | null
}

function initialHeads(): Record<Role, HeadInfo> {
  return Object.fromEntries(
    ROLES.map((r) => [r, { role: r, state: 'idle', flagCount: 0 }]),
  ) as Record<Role, HeadInfo>
}

export const initialState: DebateState = {
  dataPhase: 'standby',
  view: 'standby',
  symbol: null,
  speakerId: null,
  heads: initialHeads(),
  claims: [],
  pendingClaims: [],
  currentClaim: null,
  verdicts: [],
  result: null,
  error: null,
}

export type Action =
  | { type: 'reset' }
  | { type: 'event'; ev: DebateEvent } // 数据层:后端事件入账
  | { type: 'tick' } // 展示层:推进回放时间线

function patch(
  heads: Record<Role, HeadInfo>,
  role: Role,
  p: Partial<HeadInfo>,
): Record<Role, HeadInfo> {
  return { ...heads, [role]: { ...heads[role], ...p } }
}

const DEBATERS: Role[] = ['bull', 'bear', 'macro', 'risk']

export function debateReducer(s: DebateState, a: Action): DebateState {
  switch (a.type) {
    case 'reset':
      return { ...initialState, heads: initialHeads() }

    // ---- 数据层:把后端事件记入 state,但不抢占展示焦点 ----
    case 'event': {
      const ev = a.ev
      switch (ev.stage) {
        case 'argue': {
          let heads = s.heads
          for (const r of DEBATERS) heads = patch(heads, r, { state: 'entering' })
          return {
            ...s,
            dataPhase: 'argue',
            view: 'arguing',
            symbol: ev.symbol || null,
            heads,
          }
        }
        case 'claim': {
          const { stage: _s, ...claim } = ev
          void _s
          const c = claim as Claim
          return {
            ...s,
            claims: [...s.claims, c],
            pendingClaims: [...s.pendingClaims, c],
            heads: patch(s.heads, c.side, { confidence: c.confidence }),
          }
        }
        case 'audit':
          return { ...s, dataPhase: 'audit' }
        case 'audit_flag': {
          const { stage: _s, ...verdict } = ev
          void _s
          const v = verdict as Verdict
          const exists = s.verdicts.some((x) => x.claim_id === v.claim_id)
          const verdicts = exists
            ? s.verdicts.map((x) => (x.claim_id === v.claim_id ? v : x))
            : [...s.verdicts, v]
          const side = sideOfClaimId(v.claim_id)
          return {
            ...s,
            verdicts,
            heads: patch(s.heads, side, {
              state: 'flagged',
              flagCount: s.heads[side].flagCount + (exists ? 0 : 1),
            }),
          }
        }
        case 'synthesize':
          return { ...s, dataPhase: 'synthesize' }
        case 'result':
          return { ...s, dataPhase: 'done', result: ev.result }
        case 'error':
          return { ...s, dataPhase: 'error', view: 'done', error: ev.error }
        case 'done':
          return s
        default:
          return s
      }
    }

    // ---- 展示层:按时间线推进回放 ----
    case 'tick': {
      const dataReachedAudit =
        s.dataPhase === 'audit' ||
        s.dataPhase === 'synthesize' ||
        s.dataPhase === 'done'

      // 1) 辩论中:还有 claim → 下一条飞到圆心
      if (s.view === 'arguing' && s.pendingClaims.length > 0) {
        const next = s.pendingClaims[0]
        let heads = s.heads
        for (const r of DEBATERS) {
          if (r === next.side) heads = patch(heads, r, { state: 'speaking' })
          else if (heads[r].state === 'speaking')
            heads = patch(heads, r, { state: 'waiting' })
        }
        return {
          ...s,
          speakerId: next.side,
          currentClaim: next,
          pendingClaims: s.pendingClaims.slice(1),
          heads,
        }
      }

      // 2) 辩论播完 + 数据已到审计 → 魔鬼代言人登场
      if (
        s.view === 'arguing' &&
        s.pendingClaims.length === 0 &&
        dataReachedAudit
      ) {
        let heads = s.heads
        for (const r of DEBATERS)
          if (heads[r].state !== 'flagged')
            heads = patch(heads, r, { state: 'audited' })
        heads = patch(heads, 'audit', { state: 'speaking' })
        return {
          ...s,
          view: 'auditing',
          speakerId: 'audit',
          currentClaim: null,
          heads,
        }
      }

      // 3) 审计展示完 + 数据已收敛 → 主持收敛
      if (s.view === 'auditing' && s.dataPhase === 'done') {
        let heads = patch(s.heads, 'audit', { state: 'audited' })
        heads = patch(heads, 'chair', { state: 'speaking' })
        return { ...s, view: 'done', speakerId: 'chair', heads }
      }

      return s
    }

    default:
      return s
  }
}
