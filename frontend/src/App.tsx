import React, { useEffect, useState } from 'react'
import MotionProvider from './components/MotionProvider'
import Dashboard, { DashboardSelection } from './pages/Dashboard'
import Header from './components/Header'
import MotionNotice from './components/MotionNotice'

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [selection, setSelection] = useState<DashboardSelection | null>(null)
  const [darkMode, setDarkMode] = useState(() => {
    const stored = localStorage.getItem('youth-compass-theme')
    return stored ? stored === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode)
    localStorage.setItem('youth-compass-theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  return (
    <MotionProvider>
      <div className="app-shell min-h-screen transition-colors">
        <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus() }}>跳至儀表板內容</a>
        <div className="min-h-screen">
          <Header
            selection={selection}
            darkMode={darkMode}
            menuOpen={menuOpen}
            onCloseMenu={() => setMenuOpen(false)}
            onMenu={() => setMenuOpen(true)}
            onToggleTheme={() => setDarkMode(value => !value)}
          />
          <main id="main-content" tabIndex={-1} className="dashboard-stage mx-auto max-w-[1600px] px-3 pb-16 pt-4 sm:px-6 sm:pt-6 lg:px-8 lg:pt-8">
            <MotionNotice />
            <Dashboard onSelectionChange={setSelection} />
          </main>
        </div>
      </div>
    </MotionProvider>
  )
}
