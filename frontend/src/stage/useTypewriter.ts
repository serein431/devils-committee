import { useEffect, useRef, useState } from 'react'

// 打字机:像 ChatGPT 一样把文本一个字一个字吐出来。
// text 变化时重头开始;返回当前已显示的子串 + 是否打完。
export function useTypewriter(text: string, cps = 34): { shown: string; done: boolean } {
  const [shown, setShown] = useState('')
  const raf = useRef<number | null>(null)

  useEffect(() => {
    setShown('')
    if (!text) return
    const start = performance.now()
    const step = (now: number) => {
      const n = Math.min(text.length, Math.floor(((now - start) / 1000) * cps))
      setShown(text.slice(0, n))
      if (n < text.length) raf.current = requestAnimationFrame(step)
    }
    raf.current = requestAnimationFrame(step)
    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current)
    }
  }, [text, cps])

  return { shown, done: shown.length >= text.length }
}
