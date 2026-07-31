import React from 'react'

export default function JsonViewer({ data }: { data: any }) {
  return (
    <pre className="text-sm text-gray-300 whitespace-pre-wrap break-all">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}