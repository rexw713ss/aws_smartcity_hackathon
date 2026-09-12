import React, { useEffect, useRef, useState } from 'react'
import { useLenis } from 'lenis/react'
import Icon, { IconName } from './Icon'
import { useDashboardMotion } from './MotionProvider'

const links: { label: string; detail: string; id: string; icon: IconName }[] = [
  { label: '總覽', detail: '城市概況', id: 'overview', icon: 'layout' },
  { label: '人口趨勢', detail: '長期變化', id: 'population-trend', icon: 'trend' },
  { label: '行政區剖面', detail: '29 個行政區', id: 'district-profile', icon: 'districts' },
  { label: '年齡結構', detail: '青年年齡層', id: 'age-structure', icon: 'age' },
  { label: '遷徙預測', detail: '2026 遷出趨勢', id: 'migration-forecast', icon: 'migration' },
  { label: '教育程度', detail: '教育分布', id: 'education-levels', icon: 'education' },
  { label: '婚姻狀況', detail: '青年家庭', id: 'marriage-status', icon: 'heart' },
  { label: 'AI 助理', detail: '問答與證據', id: 'ai-assistant', icon: 'info' },
  { label: '資料與方法', detail: '來源說明', id: 'data-methods', icon: 'database' },
]

function documentLayoutTop(element: HTMLElement) {
  let top = 0
  let current: HTMLElement | null = element
  while (current) {
    top += current.offsetTop
    current = current.offsetParent as HTMLElement | null
  }
  return top
}

export default function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const lenis = useLenis()
  const { reducedMotion } = useDashboardMotion()
  const [activeSection, setActiveSection] = useState(() => window.location.hash.slice(1) || 'overview')
  const [isScrolling, setIsScrolling] = useState(false)
  const mobileNavigation = useRef<HTMLElement>(null)

  useEffect(() => {
    let frame = 0
    const updateActiveSection = () => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => {
        const headerHeight = document.querySelector('header')?.getBoundingClientRect().height ?? 80
        const marker = window.scrollY + headerHeight + 48
        const reached = links
          .map(link => ({ id: link.id, top: document.getElementById(link.id)?.offsetTop ?? Number.POSITIVE_INFINITY }))
          .filter(section => section.top <= marker)
        const nearPageEnd = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 24
        setActiveSection(nearPageEnd ? links[links.length - 1].id : (reached.at(-1)?.id ?? 'overview'))
      })
    }
    updateActiveSection()
    window.addEventListener('scroll', updateActiveSection, { passive: true })
    window.addEventListener('resize', updateActiveSection)
    window.addEventListener('hashchange', updateActiveSection)
    return () => {
      window.cancelAnimationFrame(frame)
      window.removeEventListener('scroll', updateActiveSection)
      window.removeEventListener('resize', updateActiveSection)
      window.removeEventListener('hashchange', updateActiveSection)
    }
  }, [])

  useEffect(() => {
    const navigation = mobileNavigation.current
    if (!navigation) return
    navigation.toggleAttribute('inert', !open)
    if (!open) return
    const previousFocus = document.activeElement as HTMLElement | null
    window.requestAnimationFrame(() => navigation.querySelector<HTMLAnchorElement>('[aria-current="location"], a')?.focus({ preventScroll: true }))
    const handleKeyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
      if (event.key !== 'Tab') return
      const controls = [...navigation.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)')]
      const first = controls[0], last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    document.addEventListener('keydown', handleKeyboard)
    return () => {
      document.removeEventListener('keydown', handleKeyboard)
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
    }
  }, [onClose, open])

  const selectSection = (event: React.MouseEvent<HTMLAnchorElement>, id: string) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    const section = document.getElementById(id)
    if (!section) return
    const headerHeight = document.querySelector('header')?.getBoundingClientRect().height ?? 80
    const destination = id === 'overview' ? 0 : documentLayoutTop(section) - headerHeight - 20
    window.history.pushState(null, '', `#${id}`)
    setActiveSection(id)
    onClose()
    setIsScrolling(!reducedMotion)
    if (lenis) {
      lenis.scrollTo(Math.max(0, destination), {
        duration: 1.2,
        immediate: reducedMotion,
        easing: progress => (1 - Math.cos(Math.PI * progress)) / 2,
        onComplete: () => setIsScrolling(false),
      })
    } else {
      window.scrollTo({ top: Math.max(0, destination), behavior: reducedMotion ? 'auto' : 'smooth' })
      window.setTimeout(() => setIsScrolling(false), reducedMotion ? 0 : 1200)
    }
  }

  const items = (mobile = false) => links.map(link => {
    const isActive = activeSection === link.id
    return (
      <a
        aria-current={isActive ? 'location' : undefined}
        className={mobile
          ? `group flex items-center gap-3 rounded-xl px-3 py-2.5 transition ${isActive ? 'bg-teal-400 text-[#08243a]' : 'text-slate-200 hover:bg-white/10 hover:text-white'}`
          : `group flex shrink-0 items-center gap-2 border-b-2 px-3 py-3 text-sm font-semibold transition ${isActive ? 'border-teal-500 text-teal-700 dark:text-teal-300' : 'border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white'}`}
        data-section-id={link.id}
        href={`#${link.id}`}
        key={link.id}
        onClick={event => selectSection(event, link.id)}
      >
        <span className={mobile
          ? `grid h-9 w-9 shrink-0 place-items-center rounded-lg ${isActive ? 'bg-[#08243a]/10' : 'bg-white/[0.06] text-teal-300'}`
          : `text-slate-400 transition group-hover:text-teal-600 dark:text-slate-500 dark:group-hover:text-teal-300 ${isActive ? '!text-teal-600 dark:!text-teal-300' : ''}`}>
          <Icon name={link.icon} className="h-[17px] w-[17px]" />
        </span>
        <span>
          <span className="block whitespace-nowrap leading-5">{link.label}</span>
          {mobile && <span className={`block text-xs ${isActive ? 'text-[#08243a]/70' : 'text-slate-400'}`}>{link.detail}</span>}
        </span>
      </a>
    )
  })

  return (
    <>
      <div aria-hidden="true" className={`section-scroll-progress pointer-events-none fixed left-0 right-0 z-[60] h-[3px] overflow-hidden bg-teal-400/10 transition-opacity ${isScrolling ? 'opacity-100' : 'opacity-0'}`} data-active={isScrolling} data-testid="section-scroll-progress">
        <span className={`block h-full origin-left bg-teal-500 transition-transform duration-[1200ms] ${isScrolling ? 'scale-x-100' : 'scale-x-0'}`} />
      </div>
      <nav aria-label="儀表板章節" className="hidden border-t border-slate-200/80 px-3 lg:block dark:border-white/10">
        <div className="mx-auto flex max-w-[1600px] items-center overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {items()}
        </div>
      </nav>
      <button aria-label="關閉導覽選單" className={`fixed inset-0 z-40 bg-slate-950/55 backdrop-blur-sm transition-opacity lg:hidden ${open ? 'opacity-100' : 'pointer-events-none opacity-0'}`} onClick={onClose} tabIndex={open ? 0 : -1} type="button" />
      <nav ref={mobileNavigation} aria-hidden={!open} aria-label="儀表板章節" className={`absolute inset-x-3 top-full z-50 mt-3 max-h-[calc(100vh-8rem)] overflow-y-auto rounded-2xl border border-white/10 bg-[#0b2438] p-3 shadow-2xl transition lg:hidden ${open ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-3 opacity-0'}`}>
        <div className="mb-2 flex items-center justify-between px-2 py-1">
          <div><p className="text-xs font-bold tracking-[0.14em] text-teal-300">資料導覽</p><p className="mt-0.5 text-sm text-slate-400">快速前往各項分析</p></div>
          <button aria-label="關閉選單" className="grid h-10 w-10 place-items-center rounded-xl text-slate-300 hover:bg-white/10 hover:text-white" onClick={onClose} type="button"><Icon name="x" className="h-5 w-5" /></button>
        </div>
        <div className="grid gap-1 sm:grid-cols-2">{items(true)}</div>
        <div className="mt-3 flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.05] px-3 py-2.5 text-xs text-slate-300"><span className="h-2 w-2 rounded-full bg-emerald-400" />29 個行政區資料已標準化</div>
      </nav>
    </>
  )
}
