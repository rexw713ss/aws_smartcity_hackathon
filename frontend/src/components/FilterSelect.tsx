import React, { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Icon, { IconName } from './Icon'

export type FilterOption = {
  label: string
  meta?: string
  value: string
}

type FilterSelectProps = {
  icon: IconName
  label: string
  onChange: (value: string) => void
  options: FilterOption[]
  searchable?: boolean
  value: string
}

type MenuPosition = {
  left: number
  maxHeight: number
  top: number
  width: number
}

export default function FilterSelect({ icon, label, onChange, options, searchable = false, value }: FilterSelectProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [menuPosition, setMenuPosition] = useState<MenuPosition>({ left: 12, maxHeight: 420, top: 96, width: 320 })
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([])
  const labelId = useId()
  const optionsId = `${labelId}-options`
  const selected = options.find(option => option.value === value) ?? options[0]
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return options
    return options.filter(option => `${option.label} ${option.meta ?? ''}`.toLocaleLowerCase().includes(normalized))
  }, [options, query])

  const closeMenu = useCallback((restoreFocus = false) => {
    setOpen(false)
    setQuery('')
    // Closing a portaled mobile sheet must not jump the moving page back to
    // its trigger (or tuck the neighboring year control behind the toolbar).
    if (restoreFocus) window.requestAnimationFrame(() => triggerRef.current?.focus({ preventScroll: true }))
  }, [])

  const positionMenu = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const estimatedHeight = Math.min(searchable ? 388 : options.length * 58 + 12, 420)
    const spaceBelow = window.innerHeight - rect.bottom - 16
    const opensAbove = spaceBelow < Math.min(estimatedHeight, 260) && rect.top > spaceBelow
    const top = opensAbove
      ? Math.max(12, rect.top - estimatedHeight - 10)
      : Math.min(window.innerHeight - 80, rect.bottom + 10)
    const availableHeight = opensAbove ? rect.top - 22 : window.innerHeight - top - 12

    setMenuPosition({
      left: Math.min(rect.left, Math.max(12, window.innerWidth - Math.max(rect.width, 320) - 12)),
      maxHeight: Math.max(220, Math.min(430, availableHeight)),
      top,
      width: Math.max(rect.width, 320),
    })
  }, [options.length, searchable])

  useLayoutEffect(() => {
    if (!open) return
    positionMenu()
    const frame = window.requestAnimationFrame(positionMenu)
    window.addEventListener('resize', positionMenu)
    window.addEventListener('scroll', positionMenu, true)
    return () => {
      window.cancelAnimationFrame(frame)
      window.removeEventListener('resize', positionMenu)
      window.removeEventListener('scroll', positionMenu, true)
    }
  }, [open, positionMenu])

  useEffect(() => {
    if (!open) return

    const focusFrame = window.requestAnimationFrame(() => {
      if (searchable) {
        searchRef.current?.focus()
      } else {
        const selectedIndex = filtered.findIndex(option => option.value === value)
        optionRefs.current[Math.max(0, selectedIndex)]?.focus()
      }
    })
    const closeOnOutsideClick = (event: MouseEvent) => {
      const target = event.target as Node
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) closeMenu()
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      closeMenu(true)
    }
    document.addEventListener('mousedown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('mousedown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [closeMenu, filtered, open, searchable, value])

  const choose = (option: FilterOption) => {
    onChange(option.value)
    closeMenu(true)
  }

  const focusRelativeOption = (direction: 1 | -1) => {
    const currentIndex = optionRefs.current.findIndex(option => option === document.activeElement)
    const nextIndex = currentIndex < 0
      ? Math.max(0, filtered.findIndex(option => option.value === value))
      : (currentIndex + direction + filtered.length) % filtered.length
    optionRefs.current[nextIndex]?.focus()
  }

  const menu = open ? createPortal(
    <>
      <button
        aria-label={`關閉${label}選項`}
        className="filter-scrim"
        onClick={() => closeMenu(true)}
        tabIndex={-1}
        type="button"
      />
      <div
        className="filter-menu filter-menu-portal overflow-hidden border"
        data-lenis-prevent
        onKeyDown={event => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            focusRelativeOption(event.key === 'ArrowDown' ? 1 : -1)
          }
        }}
        ref={menuRef}
        style={menuPosition}
      >
        <div className="filter-sheet-heading">
          <div>
            <span className="filter-sheet-kicker">選擇檢視方式</span>
            <p>{label}</p>
          </div>
          <button aria-label={`關閉${label}選項`} className="filter-sheet-close" onClick={() => closeMenu(true)} type="button">
            <Icon name="x" className="h-4 w-4" />
          </button>
        </div>
        {searchable && (
          <div className="filter-search-wrap">
            <div className="relative">
              <svg aria-hidden="true" className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>
              <input
                aria-label={`搜尋${label}`}
                className="search-field h-11 w-full border pl-9 pr-3 text-[15px] outline-none"
                onChange={event => setQuery(event.target.value)}
                placeholder="搜尋 29 個行政區…"
                ref={searchRef}
                value={query}
              />
            </div>
          </div>
        )}
        <div className="filter-options" id={optionsId} role="listbox" aria-label={`${label}選項`}>
          {filtered.map((option, index) => {
            const active = option.value === value
            return (
              <button
                aria-selected={active}
                className={`filter-option flex min-h-12 w-full items-start gap-3 px-3 py-3 text-left transition ${active ? 'is-selected' : ''}`}
                key={option.value}
                onClick={() => choose(option)}
                ref={element => { optionRefs.current[index] = element }}
                role="option"
                type="button"
              >
                <span className={`option-check mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border ${active ? 'is-selected' : ''}`}>
                  <Icon name="check" className="h-3 w-3" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className={`block break-words text-[15px] leading-5 ${active ? 'font-semibold' : 'font-medium'}`}>{option.label}</span>
                  {option.meta && <span className="mt-0.5 block whitespace-normal text-xs leading-[18px] text-slate-500 dark:text-slate-300">{option.meta}</span>}
                </span>
              </button>
            )
          })}
          {filtered.length === 0 && <p className="px-3 py-8 text-center text-sm text-slate-500">找不到相符行政區</p>}
        </div>
      </div>
    </>,
    document.body,
  ) : null

  return (
    <div className={`filter-select relative ${open ? 'is-open' : ''}`} ref={rootRef}>
      <span id={labelId} className="filter-label">{label}</span>
      <button
        aria-controls={optionsId}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-labelledby={labelId}
        className={`filter-trigger ${open ? 'is-open' : ''}`}
        onClick={() => setOpen(current => !current)}
        onKeyDown={event => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
          event.preventDefault()
          setOpen(true)
        }}
        ref={triggerRef}
        role="combobox"
        type="button"
      >
        <span className="filter-trigger-icon"><Icon name={icon} className="h-[18px] w-[18px]" /></span>
        <span className="min-w-0 flex-1 text-left">
          <span className="block break-words text-[15px] font-semibold leading-5">{selected?.label}</span>
          {selected?.meta && <span className="mt-0.5 block whitespace-normal text-xs leading-[18px] text-slate-500 dark:text-slate-300">{selected.meta}</span>}
        </span>
        <span className="filter-key" aria-hidden="true">⌄</span>
      </button>
      {menu}
    </div>
  )
}
