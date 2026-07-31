import React from 'react'
import EventList from './EventList'

export default function MemoryView({ events }: { events: any[] }) {
  const filter = (e: any) => 
    e.event_type === 'memory.read' || 
    e.event_type === 'memory.write' || 
    e.event_type === 'memory.delete'

  return <EventList events={events} filter={filter} title="Memory Operations" />
}