import { useRef, useEffect } from 'react'
import gsap from 'gsap'

interface Props {
  value: number
  suffix?: string
  decimals?: number
  duration?: number
  className?: string
}

export default function AnimatedNumber({ value, suffix = '', decimals = 0, duration = 1.2, className = '' }: Props) {
  const ref = useRef<HTMLSpanElement>(null)
  const objRef = useRef({ val: 0 })

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const snap = decimals > 0 ? Math.pow(10, -decimals) : 1

    const tween = gsap.to(objRef.current, {
      val: value,
      duration,
      ease: 'power2.out',
      snap: { val: snap },
      onUpdate: () => {
        el.textContent = objRef.current.val.toFixed(decimals) + suffix
      },
    })

    return () => { tween.kill() }
  }, [value, suffix, decimals, duration])

  return (
    <span ref={ref} className={className}>
      {(0).toFixed(decimals)}{suffix}
    </span>
  )
}
