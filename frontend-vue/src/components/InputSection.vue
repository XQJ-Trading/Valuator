<template>
  <div class="input-section">
    <div class="input-container">
      <textarea 
        :value="query" 
        @input="$emit('update:query', ($event.target as HTMLTextAreaElement).value)"
        placeholder="AI에게 질문하거나 복잡한 문제를 요청해보세요..."
        class="query-input"
        @keydown.ctrl.enter="$emit('stream')"
      ></textarea>
      
      <!-- 모델 선택 섹션 -->
      <div class="model-section">
        <label class="model-label">
          <span class="model-icon">🤖</span>
          AI 모델 선택
        </label>
        <select 
          :value="selectedModel" 
          @change="$emit('update:selectedModel', ($event.target as HTMLSelectElement).value)"
          class="model-select"
        >
          <option v-for="model in availableModels" :key="model" :value="model">
            {{ getModelDisplayName(model) }}
          </option>
        </select>
      </div>

      <!-- Rule 입력 섹션 -->
      <div class="rule-section">
        <label class="rule-label">
          <span class="rule-icon">📋</span>
          규칙/제약사항 (선택사항)
        </label>
        <textarea 
          :value="rule" 
          @input="$emit('update:rule', ($event.target as HTMLTextAreaElement).value)"
          placeholder="추가적인 규칙이나 제약사항을 입력하세요..."
          class="rule-input"
          @keydown.ctrl.enter="$emit('stream')"
        ></textarea>
      </div>
      <div class="input-controls">
        <div class="action-buttons">
          <button @click="$emit('send')" :disabled="loading" class="btn btn-primary">
            <span v-if="loading" class="loading-spinner"></span>
            {{ loading ? '전송중...' : '전송' }}
          </button>
          <button @click="$emit('stream')" :disabled="loading" class="btn btn-secondary">
            <span v-if="loading" class="loading-spinner"></span>
            {{ loading ? '실시간 응답' : '실시간 응답' }}
          </button>
          <button @click="$emit('clear')" class="btn btn-outline">지우기</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  query: string
  rule: string
  loading: boolean
  selectedModel: string
  availableModels: string[]
}

interface Emits {
  (e: 'update:query', value: string): void
  (e: 'update:rule', value: string): void
  (e: 'update:selectedModel', value: string): void
  (e: 'send'): void
  (e: 'stream'): void
  (e: 'clear'): void
}

defineProps<Props>()
defineEmits<Emits>()

// 모델 표시 이름 변환 함수
function getModelDisplayName(model: string): string {
  const displayNames: Record<string, string> = {
    'gemini-flash-latest': 'Gemini Flash (빠른 응답)',
    'gemini-pro-latest': 'Gemini Pro (고성능)'
  }
  return displayNames[model] || model
}
</script>

<style scoped>
/* 입력 섹션 */
.input-section {
  width: 100%;
  padding: 1.5rem 0;
}

.input-container {
  background: var(--bg-secondary);
  border: 2px solid var(--border-color);
  border-radius: var(--border-radius);
  padding: 1.5rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  position: relative;
  box-sizing: border-box;
}

.input-container::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #2563eb, #7c3aed, #059669);
  border-radius: var(--border-radius) var(--border-radius) 0 0;
}

.query-input {
  width: 100%;
  min-height: 120px;
  padding: 1.25rem;
  border: 2px solid #d1d5db;
  border-radius: var(--border-radius);
  background: #ffffff;
  color: #111827;
  font-size: 1.05rem;
  line-height: 1.6;
  resize: vertical;
  transition: var(--transition);
  font-family: inherit;
  box-sizing: border-box;
  margin: 0;
  display: block;
  font-weight: 500;
}

.query-input::placeholder {
  color: #6b7280;
  font-weight: 400;
  opacity: 1;
}

.query-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.15);
  background: #ffffff;
}

/* 모델 선택 섹션 */
.model-section {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-color);
}

.model-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.75rem;
  font-size: 0.95rem;
}

.model-icon {
  font-size: 1.1rem;
}

.model-select {
  width: 100%;
  padding: 1rem;
  border: 2px solid #d1d5db;
  border-radius: var(--border-radius);
  background: #ffffff;
  color: #111827;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: var(--transition);
  font-family: inherit;
  box-sizing: border-box;
  appearance: none;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6,9 12,15 18,9'%3e%3c/polyline%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 1rem center;
  background-size: 1rem;
  padding-right: 3rem;
}

.model-select:hover {
  border-color: #059669;
  background-color: #f0fdf4;
}

.model-select:focus {
  outline: none;
  border-color: #059669;
  box-shadow: 0 0 0 4px rgba(5, 150, 105, 0.15);
  background-color: #ffffff;
}

.model-select option {
  padding: 0.5rem;
  background: #ffffff;
  color: #111827;
}

/* Rule 입력 섹션 */
.rule-section {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-color);
}

.rule-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.75rem;
  font-size: 0.95rem;
}

.rule-icon {
  font-size: 1.1rem;
}

.rule-input {
  width: 100%;
  min-height: 80px;
  padding: 1rem;
  border: 2px solid #d1d5db;
  border-radius: var(--border-radius);
  background: #ffffff;
  color: #111827;
  font-size: 1rem;
  line-height: 1.5;
  resize: vertical;
  transition: var(--transition);
  font-family: inherit;
  box-sizing: border-box;
  margin: 0;
  display: block;
  font-weight: 400;
}

.rule-input::placeholder {
  color: #9ca3af;
  font-weight: 400;
  opacity: 1;
}

.rule-input:focus {
  outline: none;
  border-color: #7c3aed;
  box-shadow: 0 0 0 4px rgba(124, 58, 237, 0.15);
  background: #ffffff;
}

.input-controls {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-top: 1.25rem;
  gap: 1.5rem;
  flex-wrap: wrap;
  width: 100%;
  box-sizing: border-box;
  min-height: 3rem;
}

/* 버튼 스타일 */
.action-buttons {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  align-items: center;
}

.btn {
  padding: 0.75rem 1.5rem;
  border-radius: var(--border-radius);
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
  border: 2px solid;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  position: relative;
  overflow: hidden;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none !important;
}

.btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
  transition: left 0.5s ease;
}

.btn:hover:not(:disabled)::before {
  left: 100%;
}

/* 전송 버튼 (Primary) */
.btn-primary {
  background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
  color: white;
  border: 2px solid #1d4ed8;
  box-shadow: 0 6px 16px rgba(29, 78, 216, 0.4);
  font-weight: 700;
}

.btn-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, #1e40af 0%, #1d4ed8 100%);
  border-color: #1e40af;
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(29, 78, 216, 0.5);
}

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
}

/* 스트림 버튼 (Secondary) */
.btn-secondary {
  background: linear-gradient(135deg, #6d28d9 0%, #8b5cf6 100%);
  color: white;
  border: 2px solid #6d28d9;
  box-shadow: 0 6px 16px rgba(109, 40, 217, 0.4);
  font-weight: 700;
}

.btn-secondary:hover:not(:disabled) {
  background: linear-gradient(135deg, #5b21b6 0%, #6d28d9 100%);
  border-color: #5b21b6;
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(109, 40, 217, 0.5);
}

.btn-secondary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(124, 58, 237, 0.3);
}

/* 지우기 버튼 (Outline) */
.btn-outline {
  background: #f8fafc;
  color: #475569;
  border: 2px solid #94a3b8;
  box-shadow: 0 4px 12px rgba(71, 85, 105, 0.2);
  font-weight: 600;
}

.btn-outline:hover:not(:disabled) {
  background: #e2e8f0;
  color: #334155;
  border-color: #64748b;
  transform: translateY(-3px);
  box-shadow: 0 6px 20px rgba(71, 85, 105, 0.3);
}

.btn-outline:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}

/* 버튼 아이콘 애니메이션 */
.btn:hover:not(:disabled) {
  animation: button-glow 2s ease-in-out infinite;
}

@keyframes button-glow {
  0%, 100% { box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3); }
  50% { box-shadow: 0 6px 20px rgba(37, 99, 235, 0.5); }
}

.btn-secondary:hover:not(:disabled) {
  animation: button-glow-secondary 2s ease-in-out infinite;
}

@keyframes button-glow-secondary {
  0%, 100% { box-shadow: 0 4px 12px rgba(124, 58, 237, 0.3); }
  50% { box-shadow: 0 6px 20px rgba(124, 58, 237, 0.5); }
}

/* 로딩 스피너 */
.loading-spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid transparent;
  border-top: 2px solid currentColor;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 반응형 디자인 */
@media (max-width: 768px) {
  .input-section {
    padding: 1.5rem 1rem;
  }
  
  .input-controls {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }
  
  .action-buttons {
    justify-content: center;
  }
}

@media (max-width: 480px) {
  .action-buttons {
    flex-direction: column;
  }
  
  .btn {
    justify-content: center;
  }
}
</style>
