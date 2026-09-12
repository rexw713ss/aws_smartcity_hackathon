import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'
import './spatial.css'
import './mono-atlas.css'
import './assistant.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
