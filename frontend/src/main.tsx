import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './index.css'

const container = document.getElementById('root')
if (!container) {
  // Only reachable if index.html was edited. Failing loudly beats a blank page.
  throw new Error('Root element #root was not found in the document.')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
