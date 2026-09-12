import React from 'react'

export type IconName =
  | 'age'
  | 'arrow-down'
  | 'arrow-up'
  | 'arrow-up-right'
  | 'building'
  | 'calendar'
  | 'check'
  | 'database'
  | 'districts'
  | 'download'
  | 'education'
  | 'heart'
  | 'info'
  | 'layout'
  | 'menu'
  | 'migration'
  | 'moon'
  | 'percent'
  | 'sun'
  | 'trend'
  | 'users'
  | 'x'

const paths: Record<IconName, string[]> = {
  age: ['M12 13a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M5 21a7 7 0 0 1 14 0'],
  'arrow-down': ['m7 10 5 5 5-5'],
  'arrow-up': ['m7 14 5-5 5 5'],
  'arrow-up-right': ['M7 17 17 7', 'M7 7h10v10'],
  building: ['M4 21V7l8-4 8 4v14', 'M9 21v-4h6v4', 'M8 9h.01M12 9h.01M16 9h.01M8 13h.01M12 13h.01M16 13h.01'],
  calendar: ['M6 2v4M18 2v4M3 10h18', 'M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2Z'],
  check: ['m5 12 4 4L19 6'],
  database: ['M4 6c0 2 3.6 3 8 3s8-1 8-3-3.6-3-8-3-8 1-8 3Z', 'M4 6v6c0 2 3.6 3 8 3s8-1 8-3V6', 'M4 12v6c0 2 3.6 3 8 3s8-1 8-3v-6'],
  districts: ['M3 6l7-3 4 3 7-2v14l-7 2-4-3-7 3V6Z', 'M10 3v14M14 6v14'],
  download: ['M12 3v12', 'm7 10 5 5 5-5', 'M5 21h14'],
  education: ['m3 9 9-5 9 5-9 5-9-5Z', 'M7 12v5c3 2 7 2 10 0v-5', 'M21 9v6'],
  heart: ['M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6a5.5 5.5 0 0 0 1-8.8Z'],
  info: ['M12 16v-4M12 8h.01', 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z'],
  layout: ['M4 4h16v16H4z', 'M4 9h16M9 9v11'],
  menu: ['M4 7h16M4 12h16M4 17h16'],
  migration: ['M4 7h13', 'm13 0-3-3m3 3-3 3', 'M20 17H7', 'm-3 0 3-3m-3 3 3 3'],
  moon: ['M20.4 15.4A9 9 0 0 1 8.6 3.6 9 9 0 1 0 20.4 15.4Z'],
  percent: ['M19 5 5 19', 'M7 5h.01M17 19h.01'],
  sun: ['M12 4V2M12 22v-2M4.93 4.93 3.51 3.51M20.49 20.49l-1.42-1.42M4 12H2M22 12h-2M4.93 19.07l-1.42 1.42M20.49 3.51l-1.42 1.42', 'M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0Z'],
  trend: ['M3 17 9 11l4 4 8-9', 'M15 6h6v6'],
  users: ['M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2', 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75'],
  x: ['M6 6l12 12M18 6 6 18'],
}

export default function Icon({ name, className = 'h-5 w-5' }: { name: IconName; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name].map((path, index) => <path d={path} key={index} />)}
    </svg>
  )
}
