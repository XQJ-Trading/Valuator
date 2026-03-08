<template>
  <div class="gemini-logs-page">
    <!-- 헤더 -->
    <div class="page-header">
      <h1>📋 Gemini Request Logs</h1>
    </div>

    <!-- 검색 및 필터 -->
    <div class="filters-container">
      <div class="filters-row">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="파일명 검색..."
          class="filter-input"
          @input="handleSearch"
        />
        <input
          v-model="dateFrom"
          type="date"
          class="filter-input filter-date"
          placeholder="시작 날짜"
          @change="handleSearch"
        />
        <input
          v-model="dateTo"
          type="date"
          class="filter-input filter-date"
          placeholder="종료 날짜"
          @change="handleSearch"
        />
        <select v-model="selectedModel" class="filter-select" @change="handleSearch">
          <option value="">모든 모델</option>
          <option v-for="model in availableModels" :key="model" :value="model">
            {{ model }}
          </option>
        </select>
        <select v-model="sortBy" class="filter-select" @change="handleSearch">
          <option value="newest">최신순</option>
          <option value="oldest">오래된순</option>
        </select>
      </div>
    </div>

    <!-- 로그 목록 -->
    <div class="logs-container">
      <div v-if="loading" class="loading">
        <div class="spinner"></div>
        <p>로딩중...</p>
      </div>

      <div v-else-if="error" class="error">
        <p>❌ {{ error }}</p>
        <button @click="handleSearch" class="btn-retry">다시 시도</button>
      </div>

      <div v-else-if="files.length === 0" class="empty">
        <p>📭 로그 파일이 없습니다</p>
      </div>

      <div v-else class="logs-list">
        <GeminiLogCard
          v-for="log in files"
          :key="log.filename"
          :log="log"
          @download="handleDownload"
        />
      </div>
    </div>

    <!-- 푸터 (페이지네이션) -->
    <div v-if="files.length > 0 && !loading" class="page-footer">
      <div class="pagination-info">
        <span>전체 {{ total }}개 중 {{ files.length }}개 표시</span>
      </div>
      <button
        v-if="files.length < total"
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
import { ref, onMounted, computed } from 'vue'
import { useGeminiLogs } from '../composables/useGeminiLogs'
import GeminiLogCard from '../components/dev/GeminiLogCard.vue'

const {
  files,
  loading,
  error,
  fetchLogs,
  downloadLog,
} = useGeminiLogs()

// State
const currentOffset = ref(0)
const searchQuery = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const selectedModel = ref('')
const sortBy = ref<'newest' | 'oldest'>('newest')
const total = ref(0)

// Available models (extracted from files)
const availableModels = computed(() => {
  const models = new Set<string>()
  files.value.forEach(file => {
    if (file.model) {
      models.add(file.model)
    }
  })
  return Array.from(models).sort()
})

// 날짜 형식 변환 (YYYY-MM-DD -> YYYYMMDD)
function formatDateForAPI(date: string): string {
  if (!date) return ''
  return date.replace(/-/g, '')
}

async function handleSearch() {
  currentOffset.value = 0
  const result = await fetchLogs(
    20,
    0,
    searchQuery.value || undefined,
    formatDateForAPI(dateFrom.value) || undefined,
    formatDateForAPI(dateTo.value) || undefined,
    selectedModel.value || undefined,
    sortBy.value,
    false
  )
  if (result) {
    total.value = result.total
  }
}

async function loadMore() {
  currentOffset.value += 20
  const result = await fetchLogs(
    20,
    currentOffset.value,
    searchQuery.value || undefined,
    formatDateForAPI(dateFrom.value) || undefined,
    formatDateForAPI(dateTo.value) || undefined,
    selectedModel.value || undefined,
    sortBy.value,
    true
  )
  if (result) {
    total.value = result.total
  }
}

function handleDownload(filename: string) {
  downloadLog(filename)
}

onMounted(() => {
  handleSearch()
})
</script>

<style scoped>
.gemini-logs-page {
  min-height: calc(100vh - 60px);
  max-width: 1400px;
  margin: 0 auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
}

.page-header {
  margin-bottom: 1.5rem;
}

.page-header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: var(--text-primary);
}

.filters-container {
  margin-bottom: 1.5rem;
  background: var(--bg-secondary);
  padding: 1rem;
  border-radius: var(--border-radius);
}

.filters-row {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.filter-input,
.filter-select {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 0.9rem;
  transition: var(--transition);
}

.filter-input {
  flex: 1;
  min-width: 200px;
}

.filter-date {
  min-width: 150px;
  flex: 0 0 auto;
}

.filter-select {
  min-width: 150px;
  flex: 0 0 auto;
}

.filter-input:focus,
.filter-select:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.logs-container {
  flex: 1;
  margin-bottom: 1rem;
}

.logs-list {
  display: flex;
  flex-direction: column;
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
  border: 4px solid var(--border-color);
  border-top-color: var(--primary-color);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.btn-retry {
  margin-top: 1rem;
  padding: 0.5rem 1rem;
  background: var(--primary-color);
  color: white;
  border: none;
  border-radius: var(--border-radius);
  cursor: pointer;
  font-weight: 600;
  transition: var(--transition);
}

.btn-retry:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

.page-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 0;
  border-top: 1px solid var(--border-color);
}

.pagination-info {
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.btn-load-more {
  padding: 0.75rem 1.5rem;
  background: linear-gradient(135deg, var(--primary-color) 0%, #1d4ed8 100%);
  color: white;
  border: none;
  border-radius: var(--border-radius);
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
}

.btn-load-more:hover:not(:disabled) {
  background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
}

.btn-load-more:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .filters-row {
    flex-direction: column;
  }
  
  .filter-input,
  .filter-date,
  .filter-select {
    width: 100%;
    min-width: unset;
  }
  
  .page-footer {
    flex-direction: column;
    gap: 1rem;
  }
}
</style>
