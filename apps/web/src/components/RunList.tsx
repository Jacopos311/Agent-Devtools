import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getRuns } from '../services/api'

interface Run {
  id: string
  project_name: string
  status: string
  created_at: string
  duration_ms?: number
}

export default function RunList() {
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchRuns = async () => {
      try {
        const response = await getRuns()
        setRuns(response.runs)
      } catch (error) {
        console.error('Failed to load runs:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchRuns()
  }, [])

  if (loading) {
    return (
      <div className="p-8 text-center text-gray-400">
        Loading runs...
      </div>
    )
  }

  if (runs.length === 0) {
    return (
      <div className="p-8 text-center text-gray-400">
        <p>No runs found. Run your agent with <code className="bg-gray-700 px-2 py-1 rounded">agent-devtools</code> to start tracing.</p>
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-700 text-left text-gray-400">
              <th className="p-2">Project</th>
              <th className="p-2">Status</th>
              <th className="p-2">Created</th>
              <th className="p-2">Duration</th>
              <th className="p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-b border-gray-700 hover:bg-gray-800">
                <td className="p-2">{run.project_name}</td>
                <td className="p-2">
                  <span className={`px-2 py-1 rounded text-sm ${
                    run.status === 'completed' ? 'bg-green-900 text-green-300' :
                    run.status === 'failed' ? 'bg-red-900 text-red-300' :
                    'bg-yellow-900 text-yellow-300'
                  }`}>
                    {run.status}
                  </span>
                </td>
                <td className="p-2 text-gray-400">
                  {new Date(run.created_at).toLocaleString()}
                </td>
                <td className="p-2 text-gray-400">
                  {run.duration_ms ? `${run.duration_ms}ms` : '—'}
                </td>
                <td className="p-2">
                  <Link
                    to={`/runs/${run.id}`}
                    className="text-blue-400 hover:text-blue-300"
                  >
                    Inspect
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}