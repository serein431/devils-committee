import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
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

const PACE = 0
const TICK_MS = 1600

// 导航项
const NAV_ITEMS = [
  { label: 'About', href: '#about' },
  { label: 'Debate', href: '#debate' },
  { label: 'Committee', href: '#committee' },
  { label: 'Contact', href: '#contact' },
]

// 装饰性 3D 元素
const DECORATIONS = [
  { src: '/heads/bull-idle.png', className: 'decor-tl', delay: 0.1 },
  { src: '/heads/bear-idle.png', className: 'decor-bl', delay: 0.25 },
  { src: '/heads/macro-idle.png', className: 'decor-tr', delay: 0.15 },
  { src: '/heads/risk-idle.png', className: 'decor-br', delay: 0.3 },
]

export default function App() {
  const [state, dispatch] = useReducer(debateReducer, initialState)
  const [beginner, setBeginner] = useState(false)
  const [showHero, setShowHero] = useState(true)

  const onEvent = useCallback((ev: DebateEvent) => {
    dispatch({ type: 'event', ev })
  }, [])

  const { status, start } = useDebateStream(onEvent)

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
    setShowHero(false)
  }

  const started = state.view !== 'standby'
  const showAudit = state.view === 'auditing' || state.view === 'done'
  const done = state.view === 'done' && state.result

  return (
    <div className="app">
      <AnimatePresence mode="wait">
        {showHero && !started ? (
          <motion.div
            key="hero"
            className="hero-section"
            initial={{ opacity: 1 }}
            exit={{ opacity: 0, y: -50 }}
            transition={{ duration: 0.5 }}
          >
            {/* 导航栏 */}
            <nav className="navbar">
              {NAV_ITEMS.map((item, i) => (
                <motion.a
                  key={item.label}
                  href={item.href}
                  className="nav-link"
                  initial={{ opacity: 0, y: -20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.1 }}
                >
                  {item.label}
                </motion.a>
              ))}
            </nav>

            {/* 装饰性 3D 元素 */}
            {DECORATIONS.map((d) => (
              <motion.img
                key={d.className}
                src={d.src}
                className={`decor ${d.className}`}
                initial={{ opacity: 0, x: d.className.includes('l') ? -80 : 80 }}
                animate={{ opacity: 0.6, x: 0 }}
                transition={{ delay: d.delay, duration: 0.9 }}
              />
            ))}

            {/* Hero 标题 */}
            <motion.h1
              className="hero-title gradient-text"
              initial={{ opacity: 0, y: 40 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15, duration: 0.7 }}
            >
              The Devil's
              <br />
              Committee
            </motion.h1>

            {/* 副标题 */}
            <motion.p
              className="hero-subtitle"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35, duration: 0.7 }}
            >
              别人给你一个结论。我们给你一个会自我拆台的委员会。
            </motion.p>

            {/* 底部区域 */}
            <motion.div
              className="hero-bottom"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5, duration: 0.7 }}
            >
              <p className="hero-desc">
                六个 AI 角色，四种观点交锋，一次独立审计
                <br />
                只为给你一个更清醒的投资判断
              </p>
              <button className="cta-button" onClick={() => setShowHero(false)}>
                开始辩论
              </button>
            </motion.div>

            {/* 中央人物 */}
            <motion.div
              className="hero-portrait"
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.6, duration: 0.7 }}
            >
              <img src="/heads/audit-idle.png" alt="Devil's Advocate" />
            </motion.div>
          </motion.div>
        ) : (
          <motion.div
            key="main"
            className="main-section"
            initial={{ opacity: 0, y: 50 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
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

            <Stage state={state} beginner={beginner} />

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
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
