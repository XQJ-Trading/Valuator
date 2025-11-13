<template>
  <div class="detail-page">
    <div class="page-header">
      <button @click="goBack" class="btn-back">
        <span class="back-icon">←</span>
        목록으로
      </button>
      <h1>Task Rewrite Detail</h1>
      <button @click="handleDelete" class="btn-delete-header" :disabled="loading">
        🗑️ 삭제
      </button>
    </div>

    <div v-if="loading && !rewrite" class="loading">
      <div class="spinner"></div>
      <p>로딩중...</p>
    </div>

    <div v-else-if="error" class="error">
      <p>❌ {{ error }}</p>
      <button @click="loadRewrite" class="btn-retry">다시 시도</button>
    </div>

    <div v-else-if="rewrite" class="detail-container">
      <!-- 메타데이터 -->
      <div class="metadata-section">
        <div class="metadata-item">
          <span class="metadata-label">모델:</span>
          <span class="metadata-value">🤖 {{ rewrite.model }}</span>
        </div>
        <div class="metadata-item">
          <span class="metadata-label">생성일시:</span>
          <span class="metadata-value">{{ formatDateTime(rewrite.created_at) }}</span>
        </div>
        <div v-if="rewrite.custom_prompt" class="metadata-item">
          <span class="metadata-label">커스텀 프롬프트:</span>
          <span class="metadata-value">{{ rewrite.custom_prompt }}</span>
        </div>
      </div>

      <!-- 비교 뷰 -->
      <ComparisonView
        :original="rewrite.original_task"
        :rewritten="rewrite.rewritten_task"
        @copy-original="copyOriginal"
        @copy-rewritten="copyRewritten"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskRewrite } from '../composables/useTaskRewrite'
import ComparisonView from '../components/task-rewrite/ComparisonView.vue'

const route = useRoute()
const router = useRouter()
const rewriteId = route.params.id as string

const {
  currentRewrite,
  loading,
  error,
  fetchRewriteDetail,
  deleteRewrite
} = useTaskRewrite()

const rewrite = ref(currentRewrite.value)

// Rewrite 로드
async function loadRewrite() {
  const data = await fetchRewriteDetail(rewriteId)
  if (data) {
    rewrite.value = data
  }
}

// 뒤로가기
function goBack() {
  router.push('/rewrite/history')
}

// 삭제
async function handleDelete() {
  if (!confirm('이 변환 이력을 삭제하시겠습니까?')) {
    return
  }

  const success = await deleteRewrite(rewriteId)
  if (success) {
    router.push('/rewrite/history')
  }
}

// 복사 기능
async function copyText(text: string, type: string) {
  try {
    await navigator.clipboard.writeText(text)
    alert(`${type}이 클립보드에 복사되었습니다!`)
  } catch (e) {
    console.error('Failed to copy:', e)
    alert('복사에 실패했습니다.')
  }
}

function copyOriginal() {
  if (rewrite.value) {
    copyText(rewrite.value.original_task, '원본')
  }
}

function copyRewritten() {
  if (rewrite.value) {
    copyText(rewrite.value.rewritten_task, '변환 결과')
  }
}

// 날짜 포맷
function formatDateTime(timestamp: string): string {
  try {
    const date = new Date(timestamp)
    return date.toLocaleString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  } catch {
    return timestamp
  }
}

onMounted(() => {
  if (rewriteId) {
    loadRewrite()
  }
})
</script>

<style scoped>
.detail-page {
  min-height: calc(100vh - 60px);
  max-width: 1400px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  gap: 1rem;
}

.page-header h1 {
  margin: 0;
  font-size: 2rem;
  color: var(--primary-color);
  flex: 1;
  text-align: center;
}

.btn-back {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  color: var(--text-primary);
  font-size: 0.95rem;
  cursor: pointer;
  transition: var(--transition);
}

.btn-back:hover {
  background: var(--bg-secondary);
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.back-icon {
  font-size: 1.2rem;
}

.btn-delete-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: #fee2e2;
  border: 1px solid #fca5a5;
  border-radius: var(--border-radius);
  color: #dc2626;
  font-size: 0.95rem;
  cursor: pointer;
  transition: var(--transition);
}

.btn-delete-header:hover:not(:disabled) {
  background: #fecaca;
  border-color: #f87171;
}

.btn-delete-header:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.loading,
.error {
  text-align: center;
  padding: 3rem 1rem;
  color: var(--text-secondary);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #e5e7eb;
  border-top-color: var(--primary-color);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error {
  color: #dc2626;
}

.btn-retry {
  margin-top: 1rem;
  padding: 0.5rem 1.5rem;
  background: var(--primary-color);
  color: white;
  border: none;
  border-radius: var(--border-radius);
  cursor: pointer;
  font-weight: 600;
  transition: var(--transition);
}

.btn-retry:hover {
  background: #1d4ed8;
  transform: translateY(-2px);
}

.detail-container {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.metadata-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  padding: 1.25rem;
  display: flex;
  flex-wrap: wrap;
  gap: 1.5rem;
}

.metadata-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.metadata-label {
  font-weight: 600;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.metadata-value {
  color: var(--text-primary);
  font-size: 0.95rem;
}

@media (max-width: 768px) {
  .detail-page {
    padding: 1rem 0.75rem;
  }

  .page-header {
    flex-wrap: wrap;
  }

  .page-header h1 {
    font-size: 1.5rem;
    order: 3;
    width: 100%;
    margin-top: 0.5rem;
  }

  .metadata-section {
    flex-direction: column;
    gap: 1rem;
  }
}
</style>

