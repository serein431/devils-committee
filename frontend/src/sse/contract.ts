// SSE 契约 —— 精确对齐 backend/orchestration.py 的事件序列与 backend/models.py 的字段。
// 事件流:argue → claim(乱序)→ audit(可多轮)→ audit_flag(pass 不推送)→ synthesize → result(+done)

export type Role = 'bull' | 'bear' | 'macro' | 'risk' | 'audit' | 'chair'
export type Side = 'bull' | 'bear' | 'macro' | 'risk'
export type AuditStatus =
  | 'pass'
  | 'suspected_overfit'
  | 'selection_bias'
  | 'bad_data'
  | 'thin_data'
export type Severity = 'none' | 'low' | 'medium' | 'high'
export type Provenance = 'live' | 'cache' | 'precomputed' | 'mock'

export interface Evidence {
  skill: string
  skill_id?: string
  summary: string
  status: string
  mode: string
  dataset_hashes?: string[]
  evidence_refs?: string[]
  metrics?: Record<string, number | string>
  assumptions?: string[]
}

export interface Claim {
  id: string
  agent: string
  side: Side
  text: string
  plain: string
  confidence: number
  skills_used: string[]
  evidence: Evidence[]
}

export interface Verdict {
  claim_id: string
  status: AuditStatus
  reason: string
  severity: Severity
  remediation: string
  plain: string
  provenance: Provenance
  audit_skill: string
}

export interface DisagreementPoint {
  topic: string
  bull_view: string
  bear_view: string
  status: 'consensus' | 'open'
}

export interface DebateResult {
  topic: string
  claims: Claim[]
  verdicts: Verdict[]
  audit_flags: Verdict[]
  consensus: string[]
  open_disagreements: DisagreementPoint[]
  risk_boundaries: string[]
  disclaimer: string
  elapsed_sec: number
  meta: {
    symbol?: string
    modes?: string[]
    audit_engine?: string | string[]
    data_status?: string
    n_claims?: number
    skills_manifest?: {
      results?: { skill_id?: string; status?: string; mode?: string }[]
      data?: { symbol?: string; status?: string; mode?: string }
    }
    [k: string]: unknown
  }
}

// 判别联合:每个 stage 一种事件形状
export type DebateEvent =
  | { stage: 'argue'; symbol: string; msg: string }
  | ({ stage: 'claim' } & Claim)
  | { stage: 'audit'; round: number; msg: string }
  | ({ stage: 'audit_flag' } & Verdict)
  | { stage: 'synthesize'; msg: string }
  | { stage: 'result'; result: DebateResult }
  | { stage: 'done'; [k: string]: unknown }
  | { stage: 'error'; error: string }

// ---- 角色元数据(色/emoji/中文标签,复刻 index.html 调色板)----
export const ROLES: Role[] = ['bull', 'bear', 'macro', 'risk', 'audit', 'chair']

export const ROLE_META: Record<
  Role,
  { emoji: string; color: string; label: string; en: string }
> = {
  bull: { emoji: '🐂', color: '#2dd4bf', label: '多头', en: 'BULL' },
  bear: { emoji: '🐻', color: '#fb7185', label: '空头', en: 'BEAR' },
  macro: { emoji: '🌐', color: '#a78bfa', label: '宏观', en: 'MACRO' },
  risk: { emoji: '🛡️', color: '#fbbf24', label: '风控', en: 'RISK' },
  audit: { emoji: '😈', color: '#ff3b5c', label: '魔鬼代言人', en: 'AUDIT' },
  chair: { emoji: '⚖️', color: '#3fd3e6', label: '主持', en: 'CHAIR' },
}

// audit status → 中文/英文/状态色键
export const STATUS_META: Record<
  AuditStatus,
  { zh: string; en: string; tone: string }
> = {
  pass: { zh: '通过', en: 'PASS', tone: 'good' },
  selection_bias: { zh: '选择偏差', en: 'SELECTION-BIAS', tone: 'crit' },
  suspected_overfit: { zh: '过拟合', en: 'OVERFIT', tone: 'serious' },
  bad_data: { zh: '坏数据', en: 'BAD-DATA', tone: 'serious' },
  thin_data: { zh: '证据不足', en: 'THIN-DATA', tone: 'warn' },
}

export const SEVERITY_VALUE: Record<Severity, number> = {
  none: 0,
  low: 0.34,
  medium: 0.67,
  high: 1,
}

export const TONE_COLOR: Record<string, string> = {
  good: '#35c98a',
  warn: '#f0b429',
  serious: '#ff7a3d',
  crit: '#ff3b5c',
}

export const REAL_PROVENANCE = ['live', 'cache', 'precomputed']
export const isReal = (p?: string) => REAL_PROVENANCE.includes(p ?? '')

// audit_flag 不带 side,靠 claim_id 前缀反查(claim.id = `${side}-1`)
export const sideOfClaimId = (claimId: string): Side =>
  (String(claimId).split('-')[0] as Side) ?? 'bull'
