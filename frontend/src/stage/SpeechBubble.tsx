import { AnimatePresence, motion } from 'framer-motion'
import type { Claim } from '../sse/contract'
import { ROLE_META } from '../sse/contract'
import { useTypewriter } from './useTypewriter'
import './SpeechBubble.css'

interface Props {
  claim: Claim | null
  beginner: boolean
}

export function SpeechBubble({ claim, beginner }: Props) {
  return (
    <AnimatePresence mode="wait">
      {claim && <Bubble key={claim.id} claim={claim} beginner={beginner} />}
    </AnimatePresence>
  )
}

function Bubble({ claim, beginner }: { claim: Claim; beginner: boolean }) {
  const full = beginner ? claim.plain || claim.text : claim.text
  const { shown, done } = useTypewriter(full)
  const color = ROLE_META[claim.side].color

  return (
    <motion.div
      className="bubble glass"
      style={{ '--role-color': color } as React.CSSProperties}
      initial={{ opacity: 0, y: 12, scale: 0.94 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.96 }}
      transition={{ type: 'spring', stiffness: 320, damping: 26 }}
    >
      <div className="bubble-role" style={{ color }}>
        {ROLE_META[claim.side].emoji} {ROLE_META[claim.side].label}
        <span className="bubble-conf num">
          信心 {Math.round((claim.confidence ?? 0.5) * 100)}
        </span>
      </div>
      <p className="bubble-text">
        {shown}
        {!done && <span className="caret-blink">▋</span>}
      </p>
      <span className="bubble-tail" />
    </motion.div>
  )
}
