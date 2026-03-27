<template>
  <div class="rewrite-page">
    <div class="page-header">
      <h1>✏️ Task Rewrite</h1>
      <p class="page-description">자유로운 형식의 task를 구조화된 형식으로 변환합니다</p>
    </div>

    <div class="rewrite-container">
      <!-- 입력 영역 -->
      <div class="input-section">
        <label class="section-label">
          <span class="label-icon">📝</span>
          Task 입력
        </label>
        <textarea
          v-model="taskInput"
          placeholder="변환하고 싶은 task를 입력하세요..."
          class="task-input"
          rows="8"
        ></textarea>
      </div>

      <!-- 옵션 영역 -->
      <div class="options-section">
        <div class="option-group">
          <label class="option-label">
            <span class="label-icon">🤖</span>
            모델 선택
          </label>
          <select v-model="selectedModel" class="model-select">
            <option v-for="model in availableModels" :key="model" :value="model">
              {{ getModelDisplayName(model) }}
            </option>
          </select>
        </div>

        <div class="option-group">
          <label class="option-label">
            <span class="label-icon">🧠</span>
            Thinking Level (Gemini Flash/Pro)
          </label>
          <select v-model="thinkingLevel" class="model-select">
            <option value="">기본값 (비활성화)</option>
            <option value="low">Low (빠른 응답)</option>
            <option value="high">High (깊은 추론)</option>
          </select>
        </div>

        <div class="option-group">
          <label class="option-label">
            <span class="label-icon">⚙️</span>
            커스텀 프롬프트 (선택사항)
          </label>
          <textarea
            v-model="customPrompt"
            placeholder="추가 지시사항을 입력하세요..."
            class="prompt-input"
            rows="3"
          ></textarea>
        </div>
      </div>

      <!-- 실행 버튼 -->
      <div class="action-section">
        <button
          @click="handleRewrite"
          :disabled="loading || !taskInput.trim()"
          class="btn-rewrite"
        >
          <span v-if="loading" class="loading-spinner"></span>
          <span v-else class="btn-icon">✨</span>
          {{ loading ? '변환 중...' : 'Rewrite' }}
        </button>
        <button
          @click="clearAll"
          :disabled="loading"
          class="btn-clear"
        >
          지우기
        </button>
      </div>

      <!-- 에러 메시지 -->
      <div v-if="error" class="error-message">
        <span class="error-icon">❌</span>
        {{ error }}
      </div>

      <!-- 결과 영역 -->
      <div v-if="result" class="result-section">
        <div class="result-header">
          <h3>변환 결과</h3>
          <button @click="copyResult" class="btn-copy">
            <span class="copy-icon">📋</span>
            복사
          </button>
        </div>
        <div class="result-content">
          <pre class="result-text">{{ result }}</pre>
        </div>
        <div class="result-footer">
          <button @click="handleRewriteAgain" class="btn-again">
            다시 작성
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useTaskRewrite } from '../composables/useTaskRewrite'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

const taskInput = ref('')
const customPrompt = ref('')
const selectedModel = ref('')
const thinkingLevel = ref('')
const availableModels = ref<string[]>([])
const result = ref('')

const { loading, error, rewriteTask } = useTaskRewrite()

// 모델 목록 조회
async function fetchModels() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/models`)
    const data = await res.json()
    availableModels.value = data.models || []
    if (!selectedModel.value && data.default) {
      selectedModel.value = data.default
    } else if (!selectedModel.value && availableModels.value.length > 0) {
      selectedModel.value = availableModels.value[0]
    }
  } catch (e) {
    console.error('Failed to fetch models:', e)
    availableModels.value = [
      'gemini-3-flash-preview',
      'gemini-3-pro-preview'
    ]
    if (!selectedModel.value) {
      selectedModel.value = availableModels.value[0]
    }
  }
}

// Task 변환 실행
async function handleRewrite() {
  if (!taskInput.value.trim()) return

  result.value = ''
  const response = await rewriteTask({
    task: taskInput.value.trim(),
    model: selectedModel.value,
    custom_prompt: customPrompt.value.trim() || undefined,
    thinking_level: thinkingLevel.value || undefined
  })

  if (response) {
    result.value = response.rewritten_task
  }
}

// 결과 복사
async function copyResult() {
  if (!result.value) return

  try {
    await navigator.clipboard.writeText(result.value)
    alert('결과가 클립보드에 복사되었습니다!')
  } catch (e) {
    console.error('Failed to copy:', e)
    alert('복사에 실패했습니다.')
  }
}

// 다시 작성
function handleRewriteAgain() {
  result.value = ''
}

// 모두 지우기
function clearAll() {
  taskInput.value = ''
  customPrompt.value = ''
  thinkingLevel.value = ''
  result.value = ''
}

// 모델 표시 이름 변환
function getModelDisplayName(model: string): string {
  const displayNames: Record<string, string> = {
    'gemini-3-flash-preview': 'Gemini 3 Flash (빠른 응답)',
    'gemini-3-pro-preview': 'Gemini 3 Pro (고성능)',
    'gemini-2.5-flash': 'Gemini 3 Flash',
    'gemini-2.5-pro': 'Gemini 3 Pro',
    'gemini-flash-latest': 'Gemini 3 Flash',
    'gemini-pro-latest': 'Gemini 3 Pro'
  }
  return displayNames[model] || model
}

onMounted(() => {
  fetchModels()
})
</script>

<style scoped>
.rewrite-page {
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
  margin: 0 0 0.5rem;
  font-size: 2rem;
  color: var(--primary-color);
}

.page-description {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.95rem;
}

.rewrite-container {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.input-section,
.options-section,
.result-section {
  background: var(--bg-secondary);
  border: 2px solid var(--border-color);
  border-radius: var(--border-radius);
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.section-label,
.option-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  font-weight: 600;
  color: var(--text-primary);
  font-size: 0.95rem;
}

.label-icon {
  font-size: 1.1rem;
}

.task-input,
.prompt-input {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  font-family: inherit;
  font-size: 0.95rem;
  line-height: 1.6;
  resize: vertical;
  transition: var(--transition);
}

.task-input:focus,
.prompt-input:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.options-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.option-group {
  display: flex;
  flex-direction: column;
}

.model-select {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  font-family: inherit;
  font-size: 0.95rem;
  background: white;
  cursor: pointer;
  transition: var(--transition);
}

.model-select:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.action-section {
  display: flex;
  gap: 1rem;
  justify-content: center;
}

.btn-rewrite,
.btn-clear {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 2rem;
  border: none;
  border-radius: var(--border-radius);
  font-weight: 600;
  font-size: 1rem;
  cursor: pointer;
  transition: var(--transition);
}

.btn-rewrite {
  background: linear-gradient(135deg, var(--primary-color) 0%, #1d4ed8 100%);
  color: white;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
}

.btn-rewrite:hover:not(:disabled) {
  background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
}

.btn-rewrite:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-clear {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.btn-clear:hover:not(:disabled) {
  background: var(--bg-secondary);
  border-color: var(--text-secondary);
}

.loading-spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-message {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  background: #fee2e2;
  border: 1px solid #fca5a5;
  border-radius: var(--border-radius);
  color: #dc2626;
  font-weight: 500;
}

.error-icon {
  font-size: 1.2rem;
}

.result-section {
  margin-top: 1rem;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.result-header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 1.25rem;
}

.btn-copy {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  color: var(--text-primary);
  font-size: 0.9rem;
  cursor: pointer;
  transition: var(--transition);
}

.btn-copy:hover {
  background: var(--bg-secondary);
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.copy-icon {
  font-size: 0.9rem;
}

.result-content {
  background: white;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  padding: 1.5rem;
  max-height: 500px;
  overflow-y: auto;
}

.result-text {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-family: inherit;
  font-size: 0.95rem;
  line-height: 1.7;
  color: var(--text-primary);
}

.result-footer {
  margin-top: 1rem;
  display: flex;
  justify-content: center;
}

.btn-again {
  padding: 0.5rem 1.5rem;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  color: var(--text-primary);
  font-size: 0.9rem;
  cursor: pointer;
  transition: var(--transition);
}

.btn-again:hover {
  background: var(--bg-secondary);
  border-color: var(--primary-color);
  color: var(--primary-color);
}

@media (max-width: 768px) {
  .rewrite-page {
    padding: 1rem 0.75rem;
  }

  .page-header h1 {
    font-size: 1.5rem;
  }

  .input-section,
  .options-section,
  .result-section {
    padding: 1rem;
  }

  .action-section {
    flex-direction: column;
  }

  .btn-rewrite,
  .btn-clear {
    width: 100%;
    justify-content: center;
  }
}
</style>
