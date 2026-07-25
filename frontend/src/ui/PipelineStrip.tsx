import type { ViewStage } from '../state/debateReducer'
import './PipelineStrip.css'

interface Props {
  view: ViewStage
}

const STAGES: { key: string; label: string; views: ViewStage[] }[] = [
  { key: 'argue', label: '四方取证', views: ['arguing'] },
  { key: 'audit', label: '独立复核', views: ['auditing'] },
  { key: 'synth', label: '主持收敛', views: ['done'] },
]

// 三段进度:当前 view 命中的阶段 on,之前的阶段 done。
export function PipelineStrip({ view }: Props) {
  const order: ViewStage[] = ['arguing', 'auditing', 'done']
  const curIdx = order.indexOf(view)

  return (
    <div className="pipe glass">
      {STAGES.map((s, i) => {
        const active = s.views.includes(view)
        const done = i < curIdx
        return (
          <div key={s.key} className={`pstage ${active || done ? 'on' : ''} ${done ? 'done' : ''}`}>
            <span className="pstage-idx">{done ? '✓' : i + 1}</span>
            <span className="pstage-label">{s.label}</span>
            {i < STAGES.length - 1 && <span className="pstage-arrow">→</span>}
          </div>
        )
      })}
    </div>
  )
}
