import { useEffect, useState } from 'react'

const narrowQuery = '(max-width: 1023px)'

/** Drives conditional rendering of the two panes. A hidden-but-mounted pane
 * would measure 0x0, and Recharts' ResponsiveContainer cannot lay a chart out
 * at that size, so the narrow layout must unmount the inactive pane instead of
 * hiding it with CSS. */
export default function useNarrowLayout(): boolean {
  const [narrow, setNarrow] = useState(() => matchMedia(narrowQuery).matches)

  useEffect(() => {
    const query = matchMedia(narrowQuery)
    const update = () => setNarrow(query.matches)
    query.addEventListener('change', update)
    update()
    return () => query.removeEventListener('change', update)
  }, [])

  return narrow
}
