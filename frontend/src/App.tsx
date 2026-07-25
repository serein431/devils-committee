import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import './theme.css'
import './App.css'
import { CommandBar } from './ui/CommandBar'
import { PipelineStrip } from './ui/PipelineStrip'
import { Stage } from './stage/Stage'
import { AuditConsole } from './panels/AuditConsole'
import { DisagreementMap } from './panels/DisagreementMap'
import { ResultSummary } from './panels/ResultSummary'
import { ComplianceBar } from './panels/ComplianceBar'
import { useDebateStream } from './sse/useDebateStream'
import { debateReducer, initialState } from './state/debateReducer'
import type { DebateEvent } from './sse/contract'

const PACE = 0 // 后端秒发全部数据;回放节奏完全由前端 tick 控制
const TICK_MS = 1600 // 每个发言/阶段在圆心的驻留时长

export default function App() {
  const [state, dispatch] = useReducer(debateReducer, initialState)
  const [beginner, setBeginner] = useState(false)

  const onEvent = useCallback((ev: DebateEvent) => {
    dispatch({ type: 'event', ev })
  }, [])

  const { status, start } = useDebateStream(onEvent)

  // ---- 单一回放时间线:tick 逐步推进展示层(与数据到达速率解耦)----
  // 首条快速上台;之后每步驻留时间按当前论据长度自适应(让打字机打完再切)。
  const timerRef = useRef<number | null>(null)
  useEffect(() => {
    const started = state.view !== 'standby'
    const finished = state.view === 'done'
    if (!started || finished) return
    if (timerRef.current !== null) return

    const first = state.currentClaim === null && state.view === 'arguing'
    let delay: number
    if (first) {
      delay = 350
    } else if (state.currentClaim && state.view === 'arguing') {
      // 打字机 ~34 字/秒:文本时长 + 1.1s 阅读缓冲,夹在 [1.6s, 6s]
      const chars = state.currentClaim.text.length
      delay = Math.min(6000, Math.max(1600, (chars / 34) * 1000 + 1100))
    } else {
      delay = TICK_MS
    }

    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      dispatch({ type: 'tick' })
    }, delay)
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [
    state.view,
    state.currentClaim,
    state.pendingClaims,
    state.dataPhase,
    state.speakerId,
  ])

  const busy = status === 'streaming' || (state.view !== 'standby' && state.view !== 'done')

  const onSubmit = (topic: string) => {
    dispatch({ type: 'reset' })
    start(topic, PACE)
  }

  const started = state.view !== 'standby'
  const showAudit =
    state.view === 'auditing' || state.view === 'done'
  const done = state.view === 'done' && state.result

  return (
    <div className="app">
      <header className="masthead">
        <h1 className="brand gradient-text">
          反方
          <span className="brand-en">The Devil's Committee</span>
        </h1>
        <p className="tagline">
          别人给你一个<b>结论</b>。我们给你一个会<b>自我拆台</b>的委员会。
        </p>
        {state.symbol && <span className="sym-badge num">{state.symbol}</span>}
      </header>

      <CommandBar
        onSubmit={onSubmit}
        busy={busy}
        beginner={beginner}
        onToggleMode={setBeginner}
      />

      {started && <PipelineStrip view={state.view} />}

      {started && <Stage state={state} beginner={beginner} />}

      <AuditConsole verdicts={state.verdicts} active={showAudit} beginner={beginner} />

      {done && (
        <>
          <DisagreementMap
            points={state.result!.open_disagreements}
            consensus={state.result!.consensus}
          />
          <ResultSummary result={state.result!} />
        </>
      )}

      {state.dataPhase === 'error' && (
        <div className="err glass">
          出错了:{state.error} —— 检查后端是否在 8080 运行。
        </div>
      )}

      <ComplianceBar />
    </div>
  )
}
