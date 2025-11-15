import { ref } from 'vue'
import type {
  TaskRewriteHistory,
  TaskRewriteRequest,
  TaskRewriteResponse,
  TaskRewriteHistoryList
} from '../types/TaskRewrite'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

// 싱글톤 상태
const rewrites = ref<TaskRewriteHistory[]>([])
const currentRewrite = ref<TaskRewriteHistory | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

export function useTaskRewrite() {
  /**
   * Task 변환 요청
   */
  async function rewriteTask(request: TaskRewriteRequest): Promise<TaskRewriteResponse | null> {
    loading.value = true
    error.value = null

    try {
      const res = await fetch(`${API_BASE}/api/v1/task-rewrite`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(request)
      })

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || `Failed to rewrite task: ${res.statusText}`)
      }

      const data: TaskRewriteResponse = await res.json()
      
      // 목록에 추가 (최신순으로 맨 앞에)
      const history: TaskRewriteHistory = {
        rewrite_id: data.rewrite_id,
        original_task: data.original_task,
        rewritten_task: data.rewritten_task,
        model: data.model,
        custom_prompt: request.custom_prompt || null,
        created_at: data.created_at,
        metadata: {}
      }
      rewrites.value = [history, ...rewrites.value]

      return data
    } catch (e: any) {
      error.value = e.message
      console.error('Error rewriting task:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * Rewrite 이력 목록 조회
   */
  async function fetchRewrites(
    limit: number = 10,
    offset: number = 0,
    append: boolean = false
  ): Promise<TaskRewriteHistoryList | null> {
    loading.value = true
    error.value = null

    try {
      const res = await fetch(
        `${API_BASE}/api/v1/task-rewrite/history?limit=${limit}&offset=${offset}`
      )

      if (!res.ok) {
        throw new Error(`Failed to fetch rewrites: ${res.statusText}`)
      }

      const data: TaskRewriteHistoryList = await res.json()

      // append가 true면 기존 목록에 추가, false면 교체
      if (append) {
        rewrites.value = [...rewrites.value, ...data.rewrites]
      } else {
        rewrites.value = data.rewrites
      }

      return data
    } catch (e: any) {
      error.value = e.message
      console.error('Error fetching rewrites:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * 특정 Rewrite 상세 조회
   */
  async function fetchRewriteDetail(rewriteId: string): Promise<TaskRewriteHistory | null> {
    loading.value = true
    error.value = null

    try {
      const res = await fetch(`${API_BASE}/api/v1/task-rewrite/${rewriteId}`)

      if (!res.ok) {
        throw new Error(`Failed to fetch rewrite: ${res.statusText}`)
      }

      const data: TaskRewriteHistory = await res.json()
      currentRewrite.value = data
      return data
    } catch (e: any) {
      error.value = e.message
      console.error('Error fetching rewrite detail:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * Rewrite 삭제
   */
  async function deleteRewrite(rewriteId: string): Promise<boolean> {
    loading.value = true
    error.value = null

    try {
      const res = await fetch(`${API_BASE}/api/v1/task-rewrite/${rewriteId}`, {
        method: 'DELETE'
      })

      if (!res.ok) {
        throw new Error(`Failed to delete rewrite: ${res.statusText}`)
      }

      // 목록에서 제거
      rewrites.value = rewrites.value.filter(r => r.rewrite_id !== rewriteId)
      
      // 현재 선택된 항목이 삭제된 경우 초기화
      if (currentRewrite.value?.rewrite_id === rewriteId) {
        currentRewrite.value = null
      }

      return true
    } catch (e: any) {
      error.value = e.message
      console.error('Error deleting rewrite:', e)
      return false
    } finally {
      loading.value = false
    }
  }

  return {
    rewrites,
    currentRewrite,
    loading,
    error,
    rewriteTask,
    fetchRewrites,
    fetchRewriteDetail,
    deleteRewrite
  }
}

