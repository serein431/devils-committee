import { LayoutGroup, motion } from 'framer-motion'
import { AgentHead } from './AgentHead'
import { SpeechBubble } from './SpeechBubble'
import type { DebateState } from '../state/debateReducer'
import { type Role } from '../sse/contract'
import './Stage.css'

// 左右两列站位(不圆桌):左 = 多头/宏观/主持,右 = 空头/风控/审计。
// 发言者从所属侧滑到中央放大,其余留在两侧变淡等待。
const LEFT: Role[] = ['bull', 'macro', 'chair']
const RIGHT: Role[] = ['bear', 'risk', 'audit']

const spring = { type: 'spring' as const, stiffness: 230, damping: 26, mass: 0.9 }

// 入场动画变体
const benchVariants = {
  hidden: (side: 'l' | 'r') => ({
    opacity: 0,
    x: side === 'l' ? -60 : 60,
  }),
  visible: () => ({
    opacity: 1,
    x: 0,
    transition: {
      type: 'spring' as const,
      stiffness: 200,
      damping: 25,
      staggerChildren: 0.1,
      delayChildren: 0.2,
    },
  }),
}

const headVariants = {
  hidden: { opacity: 0, y: 30, scale: 0.8 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      type: 'spring' as const,
      stiffness: 260,
      damping: 24,
    },
  },
}

const spotlightVariants = {
  hidden: { opacity: 0, scale: 0.5, y: 50 },
  visible: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: {
      type: 'spring' as const,
      stiffness: 200,
      damping: 22,
    },
  },
}

interface Props {
  state: DebateState
  beginner: boolean
}

function Bench({
  roles,
  side,
  state,
}: {
  roles: Role[]
  side: 'l' | 'r'
  state: DebateState
}) {
  return (
    <motion.div
      className={`bench bench-${side}`}
      variants={benchVariants}
      initial="hidden"
      animate="visible"
      custom={side}
    >
      {roles
        .filter((r) => r !== state.speakerId)
        .map((r) => (
          <motion.div
            key={r}
            layout
            layoutId={`head-${r}`}
            className="bench-slot"
            variants={headVariants}
            transition={spring}
          >
            <AgentHead role={r} state={state.heads[r].state} size={72} showLabel />
          </motion.div>
        ))}
    </motion.div>
  )
}

export function Stage({ state, beginner }: Props) {
  const { speakerId, heads, currentClaim } = state

  return (
    <div className="stage glass">
      <LayoutGroup>
        <div className="arena">
          <Bench roles={LEFT} side="l" state={state} />

          <div className="center-col">
            {speakerId && (
              <motion.div
                layout
                layoutId={`head-${speakerId}`}
                className="spotlight"
                variants={spotlightVariants}
                initial="hidden"
                animate="visible"
                transition={spring}
              >
                <AgentHead
                  role={speakerId}
                  state={heads[speakerId].state}
                  size={180}
                  showLabel
                />
              </motion.div>
            )}
            <div className="bubble-slot">
              <SpeechBubble claim={currentClaim} beginner={beginner} />
            </div>
          </div>

          <Bench roles={RIGHT} side="r" state={state} />
        </div>
      </LayoutGroup>
    </div>
  )
}
