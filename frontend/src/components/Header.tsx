import React from 'react'
import Icon from './Icon'
import Sidebar from './Sidebar'
import { useLenis } from 'lenis/react'
import { useDashboardMotion } from './MotionProvider'
import type { DashboardSelection } from '../pages/Dashboard'

type HeaderProps = {
  darkMode: boolean
  menuOpen: boolean
  onCloseMenu: () => void
  onMenu: () => void
  onToggleTheme: () => void
  selection: DashboardSelection | null
}

export default function Header({ darkMode, menuOpen, onCloseMenu, onMenu, onToggleTheme, selection }: HeaderProps) {
  const lenis = useLenis()
  const { reducedMotion } = useDashboardMotion()
  const editFilters = () => {
    const section = document.getElementById('dashboard-filters')
    if (!section) return
    const offset = -(document.querySelector('header')?.getBoundingClientRect().height ?? 80) - 20
    const focus = () => section.querySelector<HTMLButtonElement>('[role="combobox"]')?.focus({ preventScroll: true })
    focus()
    if (lenis) lenis.scrollTo(section, { offset, duration: 1.4, immediate: reducedMotion, easing: progress => (1 - Math.cos(Math.PI * progress)) / 2, onComplete: focus })
    else { window.scrollTo({ top: section.getBoundingClientRect().top + scrollY + offset, behavior: 'auto' }); focus() }
  }
  return (
    <header className="topbar-depth app-toolbar sticky top-0 z-30 border-b backdrop-blur-xl">
      <div className="flex h-16 items-center justify-between gap-4 px-4 sm:px-6 lg:h-20 lg:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <button onClick={onMenu} className="depth-control control-surface grid h-11 w-11 place-items-center rounded-xl border text-slate-600 lg:hidden dark:text-slate-300" aria-label="開啟導覽選單" aria-expanded={menuOpen}>
            <Icon name="menu" />
          </button>
          <a className="hidden items-center gap-3 sm:flex" href="#overview">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-[#0b2438] text-teal-300 shadow-sm dark:bg-teal-400 dark:text-[#08243a]">
              <svg aria-hidden="true" className="h-6 w-6" fill="none" viewBox="0 0 28 28"><path d="M4 21.5 10.2 5l3.8 8.4L17.8 8 24 21.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" /><path d="M7 18h14" stroke="currentColor" strokeLinecap="round" strokeWidth="2.5" /></svg>
            </span>
            <span className="hidden xl:block">
              <span className="block text-[10px] font-bold tracking-[0.16em] text-teal-700 dark:text-teal-300">新北市政府</span>
              <span className="block text-sm font-bold text-slate-900 dark:text-white">青年觀測站</span>
            </span>
          </a>
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11px] font-semibold tracking-[0.13em] text-slate-400">
              <span>公共政策<span className="hidden sm:inline">智慧分析</span></span>
              <span className="hidden h-1 w-1 rounded-full bg-slate-300 sm:block" />
              <span className="hidden text-teal-600 sm:block dark:text-teal-400">官方統計資料</span>
            </div>
            <h1 className="mt-0.5 truncate text-base font-semibold tracking-tight text-slate-900 sm:text-lg dark:text-white">青年人口儀表板</h1>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="quality-badge hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 2xl:flex dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-300">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            資料品質已檢核
          </div>
          <button onClick={onToggleTheme} aria-label={darkMode ? '切換為淺色模式' : '切換為深色模式'} className="depth-control control-surface grid h-11 w-11 place-items-center rounded-xl border text-slate-600 transition hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
            <Icon name={darkMode ? 'sun' : 'moon'} className="h-[18px] w-[18px]" />
          </button>
        </div>
      </div>
      {selection && <div className="toolbar-selection">
        <div aria-label="目前的儀表板篩選條件" className="toolbar-selection-values">
          <Icon name="districts" className="h-4 w-4" />
          <span className="toolbar-district">{selection.district === 'New Taipei City' ? '新北市' : selection.district}</span>
          <span className="toolbar-year">{selection.year} 年<span className="toolbar-month">・第 {selection.month} 月</span></span>
        </div>
        <button type="button" onClick={editFilters} aria-label="調整儀表板篩選條件">調整篩選 <Icon name="arrow-up" className="h-3.5 w-3.5" /></button>
      </div>}
      <Sidebar open={menuOpen} onClose={onCloseMenu} />
    </header>
  )
}
