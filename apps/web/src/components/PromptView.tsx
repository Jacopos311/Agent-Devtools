import React from 'react'
import JsonViewer from './JsonViewer'

export default function PromptView({ events }: { events: any[] }) {
  const promptEvents = events.filter(e => e.event_type === 'prompt.assembled')

  if (promptEvents.length === 0) {
    return (
      <div className="text-center text-gray-400 py-8">
        No prompt events found
      </div>
    )
  }

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Assembled Prompt</h2>
      <div className="bg-gray-800 rounded border border-gray-700 p-4">
        <JsonViewer data={promptEvents[0].payload} />
      </div>
    </div>
  )
}