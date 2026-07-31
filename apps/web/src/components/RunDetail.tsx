import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getRun, getEvents } from '../services/api'
import Tabs from './Tabs'
import EventList from './EventList'
import PromptView from './PromptView'
import ContextView from './ContextView'
import RetrievalView from './RetrievalView'
import MemoryView from './MemoryView'
import ToolsView from './ToolsView'
import DiffViewer from './DiffViewer'

export default function RunDetail() {
  const { runId } = useParams()
  const [run, setRun] = useState<any>(null)
  const [events, setEvents] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const fetchData = async () => {
      if (!runId) return
      try {
        const [runData, eventsData] = await Promise.all([
          getRun(runId),
          getEvents(runId, 10000)
        ])
        setRun(runData)
        setEvents(eventsData.events)
      } catch (err) {
        setError('Failed to load run data')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [runId])

  if (loading) {
    return (
      <div className="p-8 text-center text-gray-400">
        Loading run data...
      </div>
    )
  }

  if (error || !run) {
    return (
      <div className="p-8 text-center text-red-400">
        {error || 'Run not found'}
      </div>
    )
  }

  const tabs = [
    {
      id: 'replay',
      label: 'Replay',
      content: <EventList events={events} title="Event Timeline" />
    },
    {
      id: 'prompt',
      label: 'Prompt',
      content: <PromptView events={events} />
    },
    {
      id: 'context',
      label: 'Context',
      content: <ContextView events={events} />
    },
    {
      id: 'retrieval',
      label: 'Retrieval',
      content: <RetrievalView events={events} />
    },
    {
      id: 'memory',
      label: 'Memory',
      content: <MemoryView events={events} />
    },
    {
      id: 'tools',
      label: 'Tools',
      content: <ToolsView events={events} />
    },
    {
      id: 'diff',
      label: 'Diff',
      content: <DiffViewer />
    }
  ]

  return (
    <div>
      <div className="p-4 bg-gray-800 border-b border-gray-700 flex items-center justify-between">
        <div>
          <Link to="/" className="text-blue-400 hover:text-blue-300 mr-4">
            ← Back
          </Link>
          <span className="font-mono">{run.project_name}</span>
          <span className="ml-4 text-gray-400 text-sm">
            {run.id}
          </span>
        </div>
        <div className="text-sm text-gray-400">
          {run.status} • {run.duration_ms ? `${run.duration_ms}ms` : '—'}
        </div>
      </div>
      <Tabs tabs={tabs} />
    </div>
  )
}