import React from 'react'
import EventList from './EventList'

export default function RetrievalView({ events }: { events: any[] }) {
  const filter = (e: any) => 
    e.event_type === 'retrieval.started' || e.event_type === 'retrieval.result'

  return <EventList events={events} filter={filter} title="Retrieval" />
}