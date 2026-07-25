import { useState } from 'react'
import './CommandBar.css'

interface Props {
  onSubmit: (topic: string) => void
  busy: boolean
  beginner: boolean
  onToggleMode: (beginner: boolean) => void
}

const EXAMPLES = [
  '600519.SH 复权、分红、因子和流动性风险',
  '300750.SZ 成长因子、波动、流动性和指数事件',
  '601318.SH 分红、股票池和风险证据',
]

export function CommandBar({ onSubmit, busy, beginner, onToggleMode }: Props) {
  const [q, setQ] = useState('')

  const fire = (text?: string) => {
    const t = (text ?? q).trim()
    if (!t || busy) return
    setQ(t)
    onSubmit(t)
  }

  return (
    <div className="cmdbar">
      <div className="cmd glass">
        <span className="caret">›</span>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fire()}
          placeholder="输入 A 股研究问题,如:600519.SH 的复权、分红、因子和流动性风险"
          spellCheck={false}
          autoComplete="off"
        />
        <button className="go" disabled={busy} onClick={() => fire()}>
          {busy ? '开庭中…' : '开庭 ⏎'}
        </button>
      </div>

      <div className="cmd-row">
        <div className="chips">
          {EXAMPLES.map((e) => (
            <button key={e} className="chip" disabled={busy} onClick={() => fire(e)}>
              {e.split(' ')[0]}
            </button>
          ))}
        </div>
        <div className="mode-toggle">
          <button className={!beginner ? 'on' : ''} onClick={() => onToggleMode(false)}>
            🔬 专家
          </button>
          <button className={beginner ? 'on' : ''} onClick={() => onToggleMode(true)}>
            🗣 小白
          </button>
        </div>
      </div>
    </div>
  )
}
