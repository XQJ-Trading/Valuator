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

      <!-- Thinking Level 선택 섹션 (Gemini 3.0 전용) -->
      <div class="thinking-section">
        <label class="thinking-label">
          <span class="thinking-icon">🧠</span>
          Thinking Level (Gemini 3.0)
        </label>
        <select 
          :value="thinkingLevel" 
          @change="$emit('update:thinkingLevel', ($event.target as HTMLSelectElement).value)"
          class="thinking-select"
        >
          <option value="">기본값 (비활성화)</option>
          <option value="low">Low (빠른 응답)</option>
          <option value="high">High (깊은 추론)</option>
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
          <button @click="$emit('stream')" :disabled="loading" class="btn btn-primary">
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
  thinkingLevel: string
}

interface Emits {
  (e: 'update:query', value: string): void
  (e: 'update:rule', value: string): void
  (e: 'update:selectedModel', value: string): void
  (e: 'update:thinkingLevel', value: string): void
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
  padding: 1rem 0;
}

.input-container {
  background: var(--bg-secondary);
  border: 2px solid var(--border-color);
  border-radius: var(--border-radius);
  padding: 1rem;
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
  min-height: 100px;
  padding: 1rem;
  border: 2px solid #d1d5db;
  border-radius: var(--border-radius);
  background: #ffffff;
  color: #111827;
  font-size: 0.95rem;
  line-height: 1.5;
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
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color);
}

.model-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
}

.model-icon {
  font-size: 1.1rem;
}

.model-select {
  width: 100%;
  padding: 0.75rem;
  border: 2px solid #d1d5db;
  border-radius: var(--border-radius);
  background: #ffffff;
  color: #111827;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  transition: var(--transition);
  font-family: inherit;
  box-sizing: border-box;
  appearance: none;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6,9 12,15 18,9'%3e%3c/polyline%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 0.75rem center;
  background-size: 0.9rem;
  padding-right: 2.5rem;
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

/* Thinking Level 선택 섹션 */
.thinking-section {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color);
}

.thinking-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
}

.thinking-icon {
  font-size: 1.1rem;
}

.thinking-select {
  width: 100%;
  padding: 0.75rem;
  border: 2px solid #d1d5db;
  border-radius: var(--border-radius);
  background: #ffffff;
  color: #111827;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  transition: var(--transition);
  font-family: inherit;
  box-sizing: border-box;
  appearance: none;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6,9 12,15 18,9'%3e%3c/polyline%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 0.75rem center;
  background-size: 0.9rem;
  padding-right: 2.5rem;
}

.thinking-select:hover {
  border-color: #7c3aed;
  background-color: #faf5ff;
}

.thinking-select:focus {
  outline: none;
  border-color: #7c3aed;
  box-shadow: 0 0 0 4px rgba(124, 58, 237, 0.15);
  background-color: #ffffff;
}

.thinking-select option {
  padding: 0.5rem;
  background: #ffffff;
  color: #111827;
}

/* Rule 입력 섹션 */
.rule-section {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color);
}

.rule-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
}

.rule-icon {
  font-size: 1.1rem;
}

.rule-input {
  width: 100%;
  min-height: 70px;
  padding: 0.75rem;
  border: 2px solid #d1d5db;
  border-radius: var(--border-radius);
  background: #ffffff;
  color: #111827;
  font-size: 0.9rem;
  line-height: 1.4;
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
  margin-top: 1rem;
  gap: 1rem;
  flex-wrap: wrap;
  width: 100%;
  box-sizing: border-box;
  min-height: 2.5rem;
}

/* 버튼 스타일 */
.action-buttons {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  align-items: center;
}

.btn {
  padding: 0.5rem 1.2rem;
  border-radius: var(--border-radius);
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
  border: 2px solid;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
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

/* 실시간 응답 버튼 (Primary) */
.btn-primary {
  background: var(--primary-color);
  color: white;
  border: 2px solid var(--primary-color);
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.4);
  font-weight: 700;
}

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
  border-color: #1d4ed8;
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.5);
}

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
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
    padding: 0.75rem 0;
  }
  
  .input-container {
    padding: 0.75rem;
  }
  
  .query-input {
    min-height: 90px;
    padding: 0.85rem;
    font-size: 0.9rem;
  }
  
  .model-select, .thinking-select, .rule-input {
    padding: 0.65rem;
    font-size: 0.85rem;
  }
  
  .model-label, .thinking-label, .rule-label {
    font-size: 0.85rem;
    margin-bottom: 0.4rem;
  }
  
  .input-controls {
    flex-direction: column;
    align-items: stretch;
    gap: 0.75rem;
    margin-top: 0.75rem;
  }
  
  .action-buttons {
    justify-content: center;
    gap: 0.4rem;
  }
  
  .btn {
    padding: 0.4rem 0.9rem;
    font-size: 0.8rem;
  }
}

@media (max-width: 480px) {
  .input-section {
    padding: 0.5rem 0;
  }
  
  .input-container {
    padding: 0.6rem;
  }
  
  .query-input {
    min-height: 80px;
    padding: 0.75rem;
    font-size: 0.85rem;
  }
  
  .model-select, .thinking-select, .rule-input {
    padding: 0.6rem;
    font-size: 0.8rem;
  }
  
  .model-label, .thinking-label, .rule-label {
    font-size: 0.8rem;
  }
  
  .action-buttons {
    flex-direction: column;
    gap: 0.3rem;
  }
  
  .btn {
    justify-content: center;
    padding: 0.35rem 0.8rem;
    font-size: 0.75rem;
  }
}
</style>
