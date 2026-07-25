import { AnimatePresence, motion } from 'framer-motion'
import { Ring } from '../charts/MiniViz'
import type { Verdict } from '../sse/contract'
import {
  ROLE_META,
  SEVERITY_VALUE,
  STATUS_META,
  TONE_COLOR,
  isReal,
  sideOfClaimId,
} from '../sse/contract'
import './AuditConsole.css'

interface Props {
  verdicts: Verdict[]
  active: boolean
  beginner: boolean
}

// 魔鬼代言人的审计控制台 —— 逐条驳回卡片,severity 环 + provenance 徽章。
export function AuditConsole({ verdicts, active, beginner }: Props) {
  if (!active) return null
  return (
    <section className="panel glass">
      <header className="panel-h">
        <span className="panel-t" style={{ color: 'var(--crit)' }}>
          😈 魔鬼代言人 · AUDIT
        </span>
        <span className="panel-sub">
          {verdicts.length
            ? `发现 ${verdicts.length} 处问题`
            : '独立复核 · 可驳回'}
        </span>
      </header>

      <div className="verdicts">
        <AnimatePresence>
          {verdicts.length === 0 && (
            <motion.div
              className="verdict-empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              <Ring sev={0.15} color={TONE_COLOR.good} />
              <div>
                <b style={{ color: 'var(--good)' }}>暂无可证实的问题</b>
                <p>这不代表标的一定可靠 —— 只是本轮论据没被抓到硬伤。</p>
              </div>
            </motion.div>
          )}

          {verdicts.map((v) => {
            const meta = STATUS_META[v.status] ?? STATUS_META.thin_data
            const color = TONE_COLOR[meta.tone]
            const sev = SEVERITY_VALUE[v.severity] ?? 0.6
            const side = sideOfClaimId(v.claim_id)
            const real = isReal(v.provenance)
            return (
              <motion.div
                key={v.claim_id}
                className="verdict-row"
                layout
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ type: 'spring', stiffness: 300, damping: 26 }}
              >
                <Ring sev={sev} color={color} />
                <div className="verdict-main">
                  <div className="verdict-top">
                    <span className="verdict-status" style={{ color }}>
                      ⚑ {ROLE_META[side].label} · {meta.en}
                    </span>
                    <span className={`prov ${real ? 'real' : ''}`}>
                      {real ? `${v.provenance.toUpperCase()} · QuantSkills` : 'MOCK'}
                    </span>
                    <span className="sev-tag">SEV {v.severity.toUpperCase()}</span>
                  </div>
                  <p className="verdict-reason">
                    {beginner ? v.plain || v.reason : v.reason}
                  </p>
                  {!beginner && v.remediation && (
                    <p className="verdict-rem">↳ {v.remediation}</p>
                  )}
                </div>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </section>
  )
}
