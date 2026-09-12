import React, { useEffect, useRef } from 'react'

/** Preserve the open composition without bobbing/skewing functional text.
 * Lenis scrolls the page; CityDepth and ChartMotion own visual motion. */
export default function FloatingScene({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}

export function FloatingElement({ children, className = '' }: {
  children: React.ReactNode; className?: string; strength?: number; phase?: number; reading?: boolean
}) {
  const shell = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!shell.current) return
    const observer = new IntersectionObserver(([entry]) => {
      if (shell.current) shell.current.dataset.inView = String(entry.isIntersecting)
    }, { rootMargin: '60px' })
    observer.observe(shell.current)
    return () => observer.disconnect()
  }, [])
  return <div ref={shell} className={`float-shell ${className}`} data-in-view="false">
    <div className="float-motion" data-testid="velocity-surface"><div className="float-bob">{children}</div></div>
  </div>
}
