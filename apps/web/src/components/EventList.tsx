import React, { useState } from 'react'
import JsonViewer from './JsonViewer'

interface EventListProps {
  events: any[]
  title?: string
  filter?: (event: any) => boolean
}

export default function EventList({ events, title, filter }: EventListProps) {
  const [expanded, setExpanded] = useState<string | null>(null)

  const filteredEvents = filter ? events.filter(filter) : events

  if (filteredEvents.length === 0) {
    return (
      <div className="text-center text-gray-400 py-8">
        No events found
      </div>
    )
  }

  return (
    <div>
      {title && <h2 className="text-lg font-semibold mb-4">{title}</h2>}
      <div className="space-y-2">
        {filteredEvents.map((event) => (
          <div key={event.id} className="bg-gray-800 rounded border border-gray-700">
            <button
              className="w-full p-3 text-left hover:bg-gray-700 transition-colors flex items-center justify-between"
              onClick={() => setExpanded(expanded === event.id ? null : event.id)}
            >
              <div>
                <span className="text-xs text-gray-400 mr-3">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
                <span className="font-mono text-sm">
                  {event.event_type}
                </span>
              </div>
              <span className="text-gray-500">
                {expanded === event.id ? '−' : '+'}
              </span>
            </button>
            {expanded === event.id && (
              <div className="p-3 border-t border-gray-700">
                <JsonViewer data={event.payload} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}