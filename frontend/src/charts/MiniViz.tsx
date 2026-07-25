// 迷你图表 —— 移植自旧 index.html 的 barMeter/divBar/ring,按指标类型选图形。

export function BarMeter({
  val,
  max,
  color,
}: {
  val: number
  max: number
  color: string
}) {
  const w = Math.max(2, Math.min(100, (Math.abs(val) / max) * 100))
  return (
    <svg width="100%" height="9" viewBox="0 0 100 9" preserveAspectRatio="none" style={{ display: 'block' }}>
      <rect x="0" y="3" width="100" height="3" rx="1.5" fill="var(--line2)" />
      <rect x="0" y="2.5" width={w} height="4" rx="2" fill={color} />
    </svg>
  )
}

export function DivBar({
  val,
  max,
  pos,
  neg,
}: {
  val: number
  max: number
  pos: string
  neg: string
}) {
  const p = Math.max(-1, Math.min(1, val / max))
  const w = Math.abs(p) * 50
  const x = p >= 0 ? 50 : 50 - w
  return (
    <svg width="100%" height="12" viewBox="0 0 100 12" preserveAspectRatio="none" style={{ display: 'block' }}>
      <rect x="0" y="4.5" width="100" height="3" rx="1.5" fill="var(--line2)" />
      <line x1="50" y1="1" x2="50" y2="11" stroke="var(--line2)" strokeWidth="1" />
      <rect x={x} y="3.5" width={Math.max(1.5, w)} height="5" rx="2" fill={p >= 0 ? pos : neg} />
    </svg>
  )
}

export function Ring({ sev, color, size = 40 }: { sev: number; color: string; size?: number }) {
  const r = 15
  const cx = 18
  const cy = 18
  const circ = 2 * Math.PI * r
  const on = circ * sev
  return (
    <svg width={size} height={size} viewBox="0 0 36 36">
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--line2)" strokeWidth="3.5" />
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeDasharray={`${on} ${circ}`}
        transform={`rotate(-90 ${cx} ${cy})`}
      />
      <text x="18" y="21.5" textAnchor="middle" fontSize="10" fill={color} fontWeight="700">
        {Math.round(sev * 100)}
      </text>
    </svg>
  )
}

const MLAB: Record<string, string> = {
  ic: '因子 IC',
  ir: '信息比 IR',
  n_obs: '样本量 n',
  window_return: '区间收益',
  adv_participation: 'ADV 占比',
  impact_bps: '冲击成本',
  car_bps: '事件异常收益',
  n_events: '事件数',
  concentration: '持仓集中',
}

// 一行指标:按 key 选图形,未知 key 退化为纯数值 chip
export function MetricRow({ k, v }: { k: string; v: number | string }) {
  const lab = MLAB[k] || k
  const num = typeof v === 'number' ? v : Number(v)
  let mid: React.ReactNode = null
  let vv = String(v)

  if (k === 'ic') {
    mid = <BarMeter val={num} max={0.1} color="var(--bull)" />
    vv = num.toFixed(3)
  } else if (k === 'ir') {
    mid = <BarMeter val={num} max={1.5} color="var(--macro)" />
    vv = num.toFixed(2)
  } else if (k === 'impact_bps') {
    mid = <BarMeter val={num} max={150} color="var(--serious)" />
    vv = `${num}bps`
  } else if (k === 'car_bps') {
    mid = <DivBar val={num} max={120} pos="var(--good)" neg="var(--bear)" />
    vv = `${num > 0 ? '+' : ''}${num}bps`
  } else if (k === 'adv_participation') {
    mid = <BarMeter val={num} max={1} color="var(--risk)" />
    vv = `${(num * 100).toFixed(0)}%`
  } else if (k === 'window_return') {
    mid = <DivBar val={num} max={0.3} pos="var(--good)" neg="var(--bear)" />
    vv = `${(num * 100).toFixed(1)}%`
  } else if (k === 'n_obs') {
    mid = <BarMeter val={num} max={300} color={num < 40 ? 'var(--warn)' : 'var(--dim)'} />
  }

  return (
    <div className="metric-row">
      <span className="metric-label">{lab}</span>
      <span className="metric-viz">{mid}</span>
      <span className="metric-val num">{vv}</span>
    </div>
  )
}
