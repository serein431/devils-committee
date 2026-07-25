import { motion } from 'framer-motion'
import type { HeadState } from '../state/debateReducer'
import { ROLE_META, type Role } from '../sse/contract'
import { HEAD_ART } from './headArt'
import './HeadPlaceholder.css'

export interface AgentHeadProps {
  role: Role
  state: HeadState
  size: number
  showLabel?: boolean
}

// 优先吃 Peeps 3D PNG(闭嘴 idle + 张嘴 talk 两态);没图回退 CSS 占位球。
export function AgentHead({ role, state, size, showLabel }: AgentHeadProps) {
  const meta = ROLE_META[role]
  const art = HEAD_ART[role]
  const speaking = state === 'speaking'
  const flagged = state === 'flagged'

  return (
    <div className="head-wrap" style={{ width: size }}>
      <motion.div
        className={`head-fig state-${state} ${art ? 'has-art' : 'no-art'}`}
        style={
          {
            width: size,
            height: size,
            '--role-color': meta.color,
          } as React.CSSProperties
        }
        animate={
          speaking
            ? { y: [0, -7, 0] }
            : flagged
              ? { x: [0, -5, 5, -3, 3, 0] }
              : { y: 0, x: 0 }
        }
        transition={
          speaking
            ? { duration: 1.5, repeat: Infinity, ease: 'easeInOut' }
            : { duration: 0.45 }
        }
      >
        {art ? (
          <div className="head-art" style={{ width: size, height: size }}>
            {/* 底图:待命/中性 */}
            <img className="art-idle" src={art.idle} alt={meta.label} draggable={false} />
            {/* 张嘴帧:说话时交替显现,营造"在讲话" */}
            {art.talk && (
              <motion.img
                className="art-talk"
                src={art.talk}
                alt=""
                draggable={false}
                animate={speaking ? { opacity: [0, 1, 0, 1, 0] } : { opacity: 0 }}
                transition={
                  speaking
                    ? { duration: 0.6, repeat: Infinity, ease: 'linear' }
                    : { duration: 0.2 }
                }
              />
            )}
          </div>
        ) : (
          // 无素材回退:CSS 伪 3D 球 + emoji
          <div
            className="head-ball"
            style={{ width: size, height: size } as React.CSSProperties}
          >
            <span className="head-emoji" style={{ fontSize: size * 0.46 }}>
              {meta.emoji}
            </span>
          </div>
        )}

        {flagged && <span className="head-flag">⚑</span>}
        {state === 'audited' && <span className="head-check">✓</span>}
      </motion.div>

      {showLabel && (
        <div className="head-label">
          <b style={{ color: meta.color }}>{meta.en}</b>
          <span>{meta.label}</span>
        </div>
      )}
    </div>
  )
}
