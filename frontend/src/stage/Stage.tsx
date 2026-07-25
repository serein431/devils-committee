import { LayoutGroup, motion, AnimatePresence } from 'framer-motion'
import { AgentHead } from './AgentHead'
import { SpeechBubble } from './SpeechBubble'
import type { DebateState } from '../state/debateReducer'
import { type Role } from '../sse/contract'
import './Stage.css'

const spring = { type: 'spring' as const, stiffness: 230, damping: 26, mass: 0.9 }

// 6个角色的固定位置（百分比）
const ROLE_POSITIONS: Record<Role, { left: string; top: string }> = {
  bull: { left: '5%', top: '10%' },      // 左上
  macro: { left: '85%', top: '10%' },    // 右上
  chair: { left: '5%', top: '75%' },     // 左下
  bear: { left: '85%', top: '75%' },     // 右下
  risk: { left: '85%', top: '42%' },     // 右中
  audit: { left: '5%', top: '42%' },     // 左中
}

interface Props {
  state: DebateState
  beginner: boolean
}

// 角落座位组件
function CornerSeat({
  role,
  state,
  isSpeaker,
}: {
  role: Role
  state: DebateState
  isSpeaker: boolean
}) {
  const pos = ROLE_POSITIONS[role]
  const headState = state.heads[role].state

  return (
    <motion.div
      className="corner-seat"
      style={{
        position: 'absolute',
        left: pos.left,
        top: pos.top,
      }}
      initial={{ opacity: 0, scale: 0.5 }}
      animate={{
        opacity: isSpeaker ? 0 : 1,
        scale: isSpeaker ? 0.5 : 1,
      }}
      transition={spring}
    >
      <AgentHead role={role} state={headState} size={80} showLabel />
    </motion.div>
  )
}

export function Stage({ state, beginner }: Props) {
  const { speakerId, heads, currentClaim } = state

  // 获取所有非发言者角色
  const allRoles: Role[] = ['bull', 'bear', 'macro', 'risk', 'audit', 'chair']
  const waitingRoles = allRoles.filter((r) => r !== speakerId)

  return (
    <div className="stage glass">
      <LayoutGroup>
        <div className="arena">
          {/* 角落座位 */}
          {waitingRoles.map((role) => (
            <CornerSeat
              key={role}
              role={role}
              state={state}
              isSpeaker={false}
            />
          ))}

          {/* 中央发言区 */}
          <div className="center-stage">
            <AnimatePresence mode="wait">
              {speakerId && (
                <motion.div
                  key={speakerId}
                  className="spotlight"
                  initial={{ opacity: 0, scale: 0.5, y: 50 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.5, y: -50 }}
                  transition={spring}
                >
                  <AgentHead
                    role={speakerId}
                    state={heads[speakerId].state}
                    size={200}
                    showLabel
                  />
                </motion.div>
              )}
            </AnimatePresence>

            <div className="bubble-slot">
              <SpeechBubble claim={currentClaim} beginner={beginner} />
            </div>
          </div>
        </div>
      </LayoutGroup>
    </div>
  )
}
