import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import './styles/app.css'

const root = document.getElementById('root')
if (!root) {
  document.body.innerHTML = '<div style="color:#e0e0e0;padding:40px;text-align:center;font-family:sans-serif">Ошибка: элемент #root не найден</div>'
} else {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  )
}
