import React, { useState, useEffect } from 'react'
import { getRuns, getDiff } from '../services/api'

export default function DiffViewer() {
  const [runs, setRuns] = useState<any[]>([])
  const [runA, setRunA] = useState('')
  const [runB, setRunB] = useState('')
  const [diff, setDiff] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const fetchRuns = async () => {
      try {
        const response = await getRuns()
        setRuns(response.runs)
        if (response.runs.length >= 2) {
          setRunA(response.runs[0].id)
          setRunB(response.runs[1].id)
        }
      } catch (error) {
        console.error('Failed to load runs for diff:', error)
      }
    }
    fetchRuns()
  }, [])

  const handleCompare = async () => {
    if (!runA || !runB) return
    setLoading(true)
    try {
      const result = await getDiff(runA, runB)
      setDiff(result)
    } catch (error) {
      console.error('Failed to compare runs:', error)
    } finally {
      setLoading(false)
    }
  }

  if (runs.length < 2) {
    return (
      <div className="text-center text-gray-400 py-8">
        Need at least 2 runs to compare
      </div>
    )
  }

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Behavior Diff</h2>
      <div className="flex gap-4 items-end mb-6">
        <div>
          <label className="block text-sm text-gray-400 mb-1">Run A (baseline)</label>
          <select
            value={runA}
            onChange={(e) => setRunA(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-3 py-2 w-64"
          >
            {runs.map(r => (
              <option key={r.id} value={r.id}>
                {r.project_name} - {r.id.slice(0,8)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm text-gray-400 mb-1">Run B (comparison)</label>
          <select
            value={runB}
            onChange={(e) => setRunB(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-3 py-2 w-64"
          >
            {runs.map(r => (
              <option key={r.id} value={r.id}>
                {r.project_name} - {r.id.slice(0,8)}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={handleCompare}
          disabled={loading || !runA || !runB}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded disabled:opacity-50"
        >
          {loading ? 'Comparing...' : 'Compare'}
        </button>
      </div>

      {diff && (
        <div>
          <div className="text-sm text-gray-400 mb-2">
            Total differences: {diff.total_differences}
          </div>
          {Object.entries(diff.differences_by_category || {}).map(([category, items]: [string, any]) => (
            <div key={category} className="mb-4">
              <h3 className="text-md font-semibold mb-2 capitalize">{category}</h3>
              <div className="space-y-2">
                {(items as any[]).map((item, idx) => (
                  <div key={idx} className="bg-gray-800 border border-gray-700 rounded p-3">
                    <div className="flex items-start gap-2">
                      <span className={`text-sm font-mono ${
                        item.type === 'added' ? 'text-green-400' :
                        item.type === 'removed' ? 'text-red-400' :
                        'text-yellow-400'
                      }`}>
                        [{item.type}]
                      </span>
                      <span className="text-sm text-gray-300">
                        {item.path}
                      </span>
                    </div>
                    {item.type === 'changed' && (
                      <div className="mt-1 text-sm">
                        <div className="text-red-400">- {JSON.stringify(item.old_value)}</div>
                        <div className="text-green-400">+ {JSON.stringify(item.new_value)}</div>
                      </div>
                    )}
                    {item.type === 'added' && (
                      <div className="mt-1 text-sm text-green-400">
                        + {JSON.stringify(item.new_value)}
                      </div>
                    )}
                    {item.type === 'removed' && (
                      <div className="mt-1 text-sm text-red-400">
                        - {JSON.stringify(item.old_value)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}