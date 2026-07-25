import { LayoutGroup, motion, AnimatePresence } from 'framer-motion'
import { AgentHead } from './AgentHead'
import { Avatar3D } from './Avatar3D'
import { SpeechBubble } from './SpeechBubble'
import type { DebateState } from '../state/debateReducer'
import { type Role } from '../sse/contract'
import './Stage.css'

const spring = { type: 'spring' as const, stiffness: 230, damping: 26, mass: 0.9 }

// 6个角色的固定位置 - 不发言时在左下/右下角
const WAITING_POSITIONS: Record<Role, { left: string; top: string }> = {
  bull: { left: '5%', top: '70%' },      // 左下
  bear: { left: '85%', top: '70%' },     // 右下
  macro: { left: '5%', top: '45%' },     // 左中
  risk: { left: '85%', top: '45%' },     // 右中
  audit: { left: '5%', top: '20%' },     // 左上
  chair: { left: '85%', top: '20%' },    // 右上
}

interface Props {
  state: DebateState
  beginner: boolean
}

// 等待座位组件 - 小尺寸 2D 头像
function WaitingSeat({
  role,
  state,
}: {
  role: Role
  state: DebateState
}) {
  const pos = WAITING_POSITIONS[role]
  const headState = state.heads[role].state

  return (
    <motion.div
      className="waiting-seat"
      style={{
        position: 'absolute',
        left: pos.left,
        top: pos.top,
      }}
      initial={{ opacity: 0, scale: 0.5 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={spring}
    >
      <AgentHead role={role} state={headState} size={64} showLabel />
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
          {/* 等待座位 - 左下/右下角 */}
          {waitingRoles.map((role) => (
            <WaitingSeat
              key={role}
              role={role}
              state={state}
            />
          ))}

          {/* 中央发言区 - 3D 模型 */}
          <div className="center-stage">
            <AnimatePresence mode="wait">
              {speakerId ? (
                <motion.div
                  key={speakerId}
                  className="spotlight-3d"
                  initial={{ opacity: 0, scale: 0.5, y: 50 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.5, y: -50 }}
                  transition={spring}
                >
                  <Avatar3D
                    role={speakerId}
                    speaking={heads[speakerId].state === 'speaking'}
                    size={280}
                  />
                  <div className="speaker-label">
                    <b style={{ color: `var(--${speakerId})` }}>
                      {speakerId.toUpperCase()}
                    </b>
                  </div>
                </motion.div>
              ) : (
                // 没有发言者时显示默认 3D 模型
                <motion.div
                  key="default"
                  className="spotlight-3d"
                  initial={{ opacity: 0, scale: 0.5 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={spring}
                >
                  <Avatar3D
                    role="audit"
                    speaking={false}
                    size={280}
                  />
                  <div className="speaker-label">
                    <b style={{ color: 'var(--sub)' }}>
                      等待发言
                    </b>
                  </div>
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
