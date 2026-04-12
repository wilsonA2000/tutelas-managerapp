import { useRef, useEffect } from 'react'
import { useSpring, useMotionValue, motion } from 'motion/react'

interface Props {
  value: number
  suffix?: string
  decimals?: number
  duration?: number
  className?: string
}

export default function AnimatedNumber({ value, suffix = '', decimals = 0, duration = 1.2, className = '' }: Props) {
  const ref = useRef<HTMLSpanElement>(null)
  const motionValue = useMotionValue(0)
  const spring = useSpring(motionValue, { duration: duration * 1000, bounce: 0 })

  useEffect(() => {
    motionValue.set(value)
  }, [value, motionValue])

  useEffect(() => {
    const unsubscribe = spring.on('change', (latest) => {
      if (ref.current) {
        ref.current.textContent = latest.toFixed(decimals) + suffix
      }
    })
    return unsubscribe
  }, [spring, decimals, suffix])

  return (
    <motion.span ref={ref} className={className}>
      {(0).toFixed(decimals)}{suffix}
    </motion.span>
  )
}
