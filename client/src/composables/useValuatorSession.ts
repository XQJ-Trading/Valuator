import { ref } from 'vue'
import { ValuatorApiClient } from '../api/ValuatorApiClient'
import type {
  ValuatorFinalDocument,
  ValuatorSessionSummary,
  ValuatorSnapshot,
  ValuatorTaskDetail
} from '../types/Valuator'

const apiClient = new ValuatorApiClient()

interface FetchSnapshotOptions {
  silent?: boolean
  keepSnapshotOnError?: boolean
  allowNotFound?: boolean
}

export function useValuatorSession() {
  const sessions = ref<ValuatorSessionSummary[]>([])
  const snapshot = ref<ValuatorSnapshot | null>(null)
  const taskDetail = ref<ValuatorTaskDetail | null>(null)
  const finalDocument = ref<ValuatorFinalDocument | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let sessionsRequestId = 0
  let snapshotRequestId = 0
  let taskDetailRequestId = 0
  let finalRequestId = 0

  async function fetchSessions(limit: number = 20, offset: number = 0) {
    const requestId = ++sessionsRequestId
    loading.value = true
    error.value = null

    try {
      const nextSessions = await apiClient.getSessions(limit, offset)
      if (requestId !== sessionsRequestId) {
        return
      }
      sessions.value = nextSessions
    } catch (err) {
      if (requestId !== sessionsRequestId) {
        return
      }
      error.value = toErrorMessage(err, 'Failed to fetch valuator sessions')
      sessions.value = []
    } finally {
      if (requestId === sessionsRequestId) {
        loading.value = false
      }
    }
  }

  async function fetchSnapshot(
    sessionId: string,
    options: FetchSnapshotOptions = {}
  ): Promise<boolean> {
    const requestId = ++snapshotRequestId
    if (!options.silent) {
      loading.value = true
    }
    error.value = null

    try {
      const nextSnapshot = await apiClient.getSnapshot(sessionId)
      if (requestId !== snapshotRequestId) {
        return false
      }
      snapshot.value = nextSnapshot
      return true
    } catch (err) {
      if (requestId !== snapshotRequestId) {
        return false
      }
      if (options.allowNotFound && getErrorStatus(err) === 404) {
        return false
      }
      error.value = toErrorMessage(err, 'Failed to fetch valuator snapshot')
      if (!options.keepSnapshotOnError) {
        snapshot.value = null
      }
      return false
    } finally {
      if (!options.silent && requestId === snapshotRequestId) {
        loading.value = false
      }
    }
  }

  async function fetchTaskDetail(sessionId: string, taskId: string) {
    const requestId = ++taskDetailRequestId
    loading.value = true
    error.value = null

    try {
      const nextTaskDetail = await apiClient.getTaskDetail(sessionId, taskId)
      if (requestId !== taskDetailRequestId) {
        return
      }
      taskDetail.value = nextTaskDetail
    } catch (err) {
      if (requestId !== taskDetailRequestId) {
        return
      }
      error.value = toErrorMessage(err, 'Failed to fetch task detail')
      taskDetail.value = null
    } finally {
      if (requestId === taskDetailRequestId) {
        loading.value = false
      }
    }
  }

  async function fetchFinalDocument(sessionId: string) {
    const requestId = ++finalRequestId
    loading.value = true
    error.value = null

    try {
      const nextFinal = await apiClient.getFinal(sessionId)
      if (requestId !== finalRequestId) {
        return
      }
      finalDocument.value = nextFinal
    } catch (err) {
      if (requestId !== finalRequestId) {
        return
      }
      error.value = toErrorMessage(err, 'Failed to fetch final report')
      finalDocument.value = null
    } finally {
      if (requestId === finalRequestId) {
        loading.value = false
      }
    }
  }

  return {
    sessions,
    snapshot,
    taskDetail,
    finalDocument,
    loading,
    error,
    fetchSessions,
    fetchSnapshot,
    fetchTaskDetail,
    fetchFinalDocument
  }
}

function toErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

function getErrorStatus(error: unknown): number | null {
  if (!(error instanceof Error)) {
    return null
  }
  if (!('status' in error)) {
    return null
  }
  const rawStatus = (error as Error & { status?: unknown }).status
  if (typeof rawStatus === 'number') {
    return rawStatus
  }
  return null
}
