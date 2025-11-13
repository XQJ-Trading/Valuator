<template>
  <div class="history-page">
    <div class="page-header">
      <h1>📋 Task Rewrite History</h1>
    </div>

    <div class="history-container">
      <div v-if="loading && rewrites.length === 0" class="loading">
        <div class="spinner"></div>
        <p>로딩중...</p>
      </div>

      <div v-else-if="error" class="error">
        <p>❌ {{ error }}</p>
        <button @click="fetchRewrites()" class="btn-retry">다시 시도</button>
      </div>

      <div v-else-if="rewrites.length === 0" class="empty">
        <p>📭 변환 이력이 없습니다</p>
      </div>

      <div v-else class="rewrites-list">
        <RewriteCard
          v-for="rewrite in rewrites"
          :key="rewrite.rewrite_id"
          :rewrite="rewrite"
          @click="handleCardClick"
          @delete="handleDelete"
        />
      </div>
    </div>

    <!-- 페이지네이션 -->
    <div v-if="!loading && rewrites.length > 0" class="page-footer">
      <button
        @click="loadMore"
        :disabled="loading"
        class="btn-load-more"
      >
        {{ loading ? '로딩중...' : '더 보기' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskRewrite } from '../composables/useTaskRewrite'
import RewriteCard from '../components/task-rewrite/RewriteCard.vue'

const router = useRouter()
const {
  rewrites,
  loading,
  error,
  fetchRewrites,
  deleteRewrite
} = useTaskRewrite()

const currentOffset = ref(0)
const limit = 10

// 초기 로드
onMounted(() => {
  if (rewrites.value.length === 0) {
    fetchRewrites(limit, 0)
  }
})

// 카드 클릭 핸들러
function handleCardClick(rewriteId: string) {
  router.push(`/rewrite/history/${rewriteId}`)
}

// 삭제 핸들러
async function handleDelete(rewriteId: string) {
  if (!confirm('이 변환 이력을 삭제하시겠습니까?')) {
    return
  }

  const success = await deleteRewrite(rewriteId)
  if (success) {
    // 목록 새로고침
    currentOffset.value = 0
    await fetchRewrites(limit, 0)
  }
}

// 더 보기
async function loadMore() {
  currentOffset.value += limit
  await fetchRewrites(limit, currentOffset.value, true)
}
</script>

<style scoped>
.history-page {
  min-height: calc(100vh - 60px);
  max-width: 1000px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

.page-header {
  text-align: center;
  margin-bottom: 2rem;
}

.page-header h1 {
  margin: 0;
  font-size: 2rem;
  color: var(--primary-color);
}

.history-container {
  margin-bottom: 2rem;
}

.loading,
.error,
.empty {
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

.rewrites-list {
  display: flex;
  flex-direction: column;
}

.page-footer {
  display: flex;
  justify-content: center;
  padding: 2rem 0;
}

.btn-load-more {
  padding: 0.75rem 2rem;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  color: var(--text-primary);
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.btn-load-more:hover:not(:disabled) {
  background: var(--bg-secondary);
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.btn-load-more:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .history-page {
    padding: 1rem 0.75rem;
  }

  .page-header h1 {
    font-size: 1.5rem;
  }
}
</style>

