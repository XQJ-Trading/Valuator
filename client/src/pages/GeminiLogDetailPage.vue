<template>
  <div class="gemini-log-detail-page">
    <!-- 헤더 -->
    <div class="page-header">
      <button @click="goBack" class="btn-back">← 목록으로</button>
      <h1>{{ logDetail?.filename || 'Loading...' }}</h1>
    </div>

    <!-- 메타데이터 -->
    <div v-if="logDetail?.metadata" class="metadata-section">
      <div class="metadata-grid">
        <div class="metadata-item">
          <span class="metadata-label">📅 날짜</span>
          <span class="metadata-value">{{ formatDateTime(logDetail.metadata) }}</span>
        </div>
        <div class="metadata-item" v-if="logDetail.metadata.model">
          <span class="metadata-label">🤖 모델</span>
          <span class="metadata-value">{{ logDetail.metadata.model }}</span>
        </div>
        <div class="metadata-item">
          <span class="metadata-label">📦 크기</span>
          <span class="metadata-value">{{ logDetail.metadata.size_formatted }}</span>
        </div>
        <div class="metadata-item">
          <button @click="handleDownload" class="btn-download">⬇️ 다운로드</button>
        </div>
      </div>
    </div>

    <!-- JSON 뷰어 -->
    <div class="viewer-section">
      <div v-if="loading" class="loading">
        <div class="spinner"></div>
        <p>로딩중...</p>
      </div>

      <div v-else-if="error" class="error">
        <p>❌ {{ error }}</p>
        <button @click="loadLog" class="btn-retry">다시 시도</button>
      </div>

      <JsonViewer v-else-if="logDetail?.data" :data="logDetail.data" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useGeminiLogs } from '../composables/useGeminiLogs'
import JsonViewer from '../components/dev/JsonViewer.vue'

interface Props {
  filename?: string
}

const props = defineProps<Props>()
const route = useRoute()
const router = useRouter()

const {
  currentLog: logDetail,
  loading,
  error,
  fetchLogDetail,
  downloadLog,
} = useGeminiLogs()

const filename = computed(() => {
  return props.filename || (route.params.filename as string) || ''
})

function formatDateTime(metadata: any): string {
  if (metadata.date && metadata.time) {
    return `${metadata.date} ${metadata.time}`
  }
  if (metadata.datetime) {
    try {
      const date = new Date(metadata.datetime)
      return date.toLocaleString('ko-KR')
    } catch {
      return metadata.timestamp || '-'
    }
  }
  return metadata.timestamp || '-'
}

async function loadLog() {
  if (filename.value) {
    await fetchLogDetail(filename.value)
  }
}

function goBack() {
  router.push('/dev/gemini-logs')
}

function handleDownload() {
  if (logDetail.value?.filename) {
    downloadLog(logDetail.value.filename)
  }
}

onMounted(() => {
  loadLog()
})
</script>


<style scoped>
.gemini-log-detail-page {
  min-height: calc(100vh - 60px);
  max-width: 1600px;
  margin: 0 auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.btn-back {
  padding: 0.5rem 1rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  color: var(--text-primary);
  cursor: pointer;
  transition: var(--transition);
  font-weight: 500;
}

.btn-back:hover {
  background: var(--bg-tertiary);
  border-color: var(--primary-color);
}

.page-header h1 {
  margin: 0;
  font-size: 1.25rem;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.metadata-section {
  margin-bottom: 1.5rem;
  background: var(--bg-secondary);
  padding: 1rem;
  border-radius: var(--border-radius);
  border: 1px solid var(--border-color);
}

.metadata-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
  align-items: center;
}

.metadata-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.metadata-label {
  font-size: 0.85rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.metadata-value {
  font-size: 0.95rem;
  color: var(--text-primary);
  font-weight: 600;
}

.btn-download {
  padding: 0.5rem 1rem;
  background: linear-gradient(135deg, var(--primary-color) 0%, #1d4ed8 100%);
  color: white;
  border: none;
  border-radius: var(--border-radius);
  cursor: pointer;
  font-weight: 600;
  transition: var(--transition);
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
}

.btn-download:hover {
  background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
}

.viewer-section {
  flex: 1;
  min-height: 600px;
  display: flex;
  flex-direction: column;
}

.loading,
.error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem;
  color: var(--text-secondary);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid var(--border-color);
  border-top-color: var(--primary-color);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 1rem;
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

@media (max-width: 768px) {
  .page-header {
    flex-wrap: wrap;
  }
  
  .page-header h1 {
    font-size: 1rem;
  }
  
  .metadata-grid {
    grid-template-columns: 1fr;
  }
}
</style>

