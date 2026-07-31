import React from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import RunList from './components/RunList'
import RunDetail from './components/RunDetail'

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-900 text-gray-100">
        <div className="p-4 bg-gray-800 border-b border-gray-700">
          <h1 className="text-xl font-mono">Agent DevTools</h1>
        </div>
        <Routes>
          <Route path="/" element={<RunList />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}

export default App