import React from 'react'
import ReactDOM from 'react-dom/client'

import App from './App'
import './style.css'

ReactDOM.createRoot(document.querySelector<HTMLDivElement>('#app')!).render(
  React.createElement(React.StrictMode, null, React.createElement(App)),
)
