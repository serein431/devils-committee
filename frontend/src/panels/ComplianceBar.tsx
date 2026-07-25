// 常驻合规声明 —— 硬红线,组件层面就不提供任何买卖/目标价展示槽。
export function ComplianceBar() {
  return (
    <footer
      style={{
        textAlign: 'center',
        margin: '30px 0 12px',
        fontSize: 11.5,
        color: 'var(--dim)',
        letterSpacing: 0.3,
        lineHeight: 1.6,
      }}
    >
      仅供学习与研究 · 不构成任何投资建议 · 不给买卖 / 目标价 / 收益承诺 · TEAM
      ADVX2026
    </footer>
  )
}
