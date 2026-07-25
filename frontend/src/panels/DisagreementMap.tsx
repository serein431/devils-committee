import { motion } from 'framer-motion'
import type { DisagreementPoint } from '../sse/contract'
import './DisagreementMap.css'

interface Props {
  points: DisagreementPoint[]
  consensus: string[]
}

// 分歧地图 —— diverging track:左端 bull 观点、右端 bear 观点,open=仍在吵。
export function DisagreementMap({ points, consensus }: Props) {
  const open = points.filter((p) => p.status === 'open').length
  const cons = points.length - open
  return (
    <section className="panel glass">
      <header className="panel-h">
        <span className="panel-t">🗺️ 分歧地图 · DISAGREEMENT MAP</span>
        <span className="panel-sub">
          仍在吵 {open} · 已收敛 {cons}
        </span>
      </header>

      <div className="dmap">
        {points.map((p, idx) => {
          const isOpen = p.status === 'open'
          return (
            <motion.div
              key={idx}
              className="drow"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.06 }}
            >
              <div className="dtop">
                <span className="dtopic">{p.topic}</span>
                <span className={`dpill ${isOpen ? 'open' : 'cons'}`}>
                  {isOpen ? '◐ 仍在吵' : '● 已收敛'}
                </span>
              </div>
              <div className={`track ${isOpen ? 'opened' : ''}`}>
                <span className="track-mid" />
                <span className="track-lab l">{p.bull_view}</span>
                <span className="track-lab r">{p.bear_view}</span>
              </div>
            </motion.div>
          )
        })}

        {consensus.length > 0 && (
          <div className="dcons">
            <b>双方共识 ▸</b> {consensus.join('　·　')}
          </div>
        )}
      </div>
    </section>
  )
}
