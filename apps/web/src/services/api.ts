import axios from 'axios'

const API_BASE = 'http://localhost:8787'

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
})

export const getRuns = async (limit = 50, offset = 0) => {
  const response = await api.get('/runs', { params: { limit, offset } })
  return response.data
}

export const getRun = async (runId: string) => {
  const response = await api.get(`/runs/${runId}`)
  return response.data
}

export const getEvents = async (runId: string, limit = 1000, offset = 0) => {
  const response = await api.get(`/runs/${runId}/events`, { params: { limit, offset } })
  return response.data
}

export const exportRun = async (runId: string) => {
  const response = await api.get(`/runs/${runId}/export`)
  return response.data
}

export const importRun = async (data: any) => {
  const response = await api.post('/runs/import', data)
  return response.data
}

export const getDiff = async (runA: string, runB: string) => {
  const response = await api.post('/runs/diff', { run_a_id: runA, run_b_id: runB })
  return response.data
}