import React from 'react'
import EventList from './EventList'

export default function ToolsView({ events }: { events: any[] }) {
  const filter = (e: any) => 
    e.event_type === 'tool.called' || e.event_type === 'tool.result'

  return <EventList events={events} filter={filter} title="Tool Calls" />
}