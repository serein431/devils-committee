import type { DebateResult } from '../sse/contract'
import './ResultSummary.css'

interface Props {
  result: DebateResult
}

// 结果区 —— 合规红线 RECOMMENDATION:NONE + 风险边界清单 + 免责声明 + trace。
export function ResultSummary({ result }: Props) {
  const m = result.meta ?? {}
  const skillResults = m.skills_manifest?.results ?? []
  const engine = Array.isArray(m.audit_engine)
    ? m.audit_engine.join('/')
    : m.audit_engine || 'unknown'
  const modes = Array.isArray(m.modes) ? m.modes.join('/') : 'unknown'

  return (
    <section className="result-wrap">
      <div className="recbar glass">
        <span className="rec-k">RECOMMENDATION: NONE</span>
        <span className="rec-v">
          本庭<b>不给买卖、不给目标价、不承诺收益</b> —— 只教你判断,不替你决定。
        </span>
      </div>

      {result.risk_boundaries.length > 0 && (
        <ul className="bounds">
          {result.risk_boundaries.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}

      {result.disclaimer && <p className="disc">{result.disclaimer}</p>}

      <p className="trace">
        TRACE ▸ 标的 {m.symbol || '—'} · 证据模式 {modes} · 审计引擎 {engine} ·
        QuantSkills:{' '}
        {skillResults.length
          ? skillResults
              .map(
                (s) =>
                  `${s.skill_id ?? '?'}[${s.status ?? '?'}/${s.mode ?? '?'}]`,
              )
              .join(' ')
          : '无可用结果'}
      </p>
    </section>
  )
}
