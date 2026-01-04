import { ref } from 'vue'

export interface GeminiLogFile {
  filename: string
  timestamp: string
  date: string
  time: string
  size: number
  size_formatted: string
  model?: string
}

export interface GeminiLogDetail {
  filename: string
  metadata: {
    timestamp: string
    date: string | null
    time: string | null
    datetime: string | null
    size: number
    size_formatted: string
    model?: string
  }
  data: any
}

export interface GeminiLogsResponse {
  files: GeminiLogFile[]
  total: number
  limit: number
  offset: number
}

// 싱글톤 상태 (모든 컴포넌트에서 공유)
const files = ref<GeminiLogFile[]>([])
const currentLog = ref<GeminiLogDetail | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

export function useGeminiLogs() {
  /**
   * 로그 파일 목록 조회
   */
  async function fetchLogs(
    limit: number = 20,
    offset: number = 0,
    search?: string,
    dateFrom?: string,
    dateTo?: string,
    model?: string,
    sort: 'newest' | 'oldest' | 'size' = 'newest',
    append: boolean = false
  ) {
    loading.value = true
    error.value = null

    try {
      const params = new URLSearchParams({
        limit: limit.toString(),
        offset: offset.toString(),
        sort,
      })

      if (search) params.append('search', search)
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      if (model) params.append('model', model)

      const res = await fetch(`${API_BASE}/api/v1/dev/gemini-logs?${params}`)

      if (!res.ok) {
        throw new Error(`Failed to fetch logs: ${res.statusText}`)
      }

      const data: GeminiLogsResponse = await res.json()

      // append가 true면 기존 목록에 추가, false면 교체
      if (append) {
        files.value = [...files.value, ...(data.files || [])]
      } else {
        files.value = data.files || []
      }

      return data
    } catch (e: any) {
      error.value = e.message
      console.error('Error fetching Gemini logs:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * 특정 로그 파일 상세 조회
   */
  async function fetchLogDetail(filename: string) {
    loading.value = true
    error.value = null

    try {
      const res = await fetch(`${API_BASE}/api/v1/dev/gemini-logs/${encodeURIComponent(filename)}`)

      if (!res.ok) {
        throw new Error(`Failed to fetch log detail: ${res.statusText}`)
      }

      const data: GeminiLogDetail = await res.json()
      currentLog.value = data
      return data
    } catch (e: any) {
      error.value = e.message
      console.error('Error fetching log detail:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * 로그 파일 다운로드
   */
  function downloadLog(filename: string) {
    const url = `${API_BASE}/api/v1/dev/gemini-logs/${encodeURIComponent(filename)}/download`
    window.open(url, '_blank')
  }

  /**
   * 상태 초기화
   */
  function clearLogs() {
    files.value = []
    currentLog.value = null
    error.value = null
  }

  return {
    // State
    files,
    currentLog,
    loading,
    error,

    // Methods
    fetchLogs,
    fetchLogDetail,
    downloadLog,
    clearLogs,
  }
}

