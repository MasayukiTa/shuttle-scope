import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/globals.css'
// Material Symbols (Outlined) ローカルフォント。CSP / 外部 CDN 不要。
// 新規 UI のアイコンは @/components/common/MIcon 経由で利用する。
import 'material-symbols/outlined.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
