import { useCallback, useRef, useState } from 'react'
import type { DebateEvent } from './contract'

// 合约是 POST + body,EventSource 只支持 GET,所以用 fetch + ReadableStream。
// 解析循环移植自旧 web/index.html 的 run():按 "\n\n" 切事件,取 data: 行 JSON.parse。

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error'

interface UseDebateStream {
  status: StreamStatus
  start: (topic: string, pace?: number) => void
  abort: () => void
}

export function useDebateStream(
  onEvent: (ev: DebateEvent) => void,
): UseDebateStream {
  const [status, setStatus] = useState<StreamStatus>('idle')
  const abortRef = useRef<AbortController | null>(null)

  const abort = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  const start = useCallback(
    (topic: string, pace = 0.6) => {
      const q = topic.trim()
      if (!q) return
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac
      setStatus('streaming')

      const runStream = async () => {
        const res = await fetch(`/a2a?stream=1&pace=${pace}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
          },
          body: JSON.stringify({ skill: 'debate_case', topic: q }),
          signal: ac.signal,
        })
        if (!res.body) throw new Error('no stream body')
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        for (;;) {
          const { value, done } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          let i: number
          while ((i = buf.indexOf('\n\n')) >= 0) {
            const chunk = buf.slice(0, i)
            buf = buf.slice(i + 2)
            const line = chunk.split('\n').find((l) => l.startsWith('data:'))
            if (line) {
              try {
                onEvent(JSON.parse(line.slice(5).trim()) as DebateEvent)
              } catch {
                /* 跳过坏行,保持流健壮 */
              }
            }
          }
        }
        setStatus('done')
      }

      const runFallback = async () => {
        // 流失败时退回非流式 JSON,一次性还原成事件序列(与旧前端同策略)
        const r = await fetch('/a2a', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ skill: 'debate_case', topic: q }),
          signal: ac.signal,
        })
        const d = (await r.json()).result
        onEvent({ stage: 'argue', symbol: d.meta?.symbol ?? '', msg: '' })
        for (const c of d.claims ?? []) onEvent({ stage: 'claim', ...c })
        onEvent({ stage: 'audit', round: 0, msg: '' })
        for (const v of d.audit_flags ?? []) onEvent({ stage: 'audit_flag', ...v })
        onEvent({ stage: 'synthesize', msg: '' })
        onEvent({ stage: 'result', result: d })
        setStatus('done')
      }

      runStream().catch(() => {
        if (ac.signal.aborted) return
        runFallback().catch(() => {
          if (!ac.signal.aborted) setStatus('error')
        })
      })
    },
    [onEvent],
  )

  return { status, start, abort }
}
