import React from 'react'
import EventList from './EventList'

export default function ContextView({ events }: { events: any[] }) {
  const filter = (e: any) => 
    e.event_type === 'context.injected' || e.event_type === 'state.snapshot'

  return <EventList events={events} filter={filter} title="Context & State" />
}