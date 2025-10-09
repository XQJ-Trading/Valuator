<template>
  <div class="message-card" :class="`message-${message.type}`">
    <div class="message-header">
      <span class="message-icon">{{ getMessageIcon(message.type) }}</span>
      <span class="message-title">{{ getMessageTitle(message.type) }}</span>
      <span class="message-timestamp">{{ formatTime(message.timestamp) }}</span>
      <button @click="copyMessage(message.content)" class="copy-btn" title="복사">📋</button>
    </div>
    <div class="message-content">
      <div class="message-text" v-if="message.type === 'thought'">
        <em>"{{ message.content }}"</em>
      </div>
      <div class="message-text markdown-body" v-else-if="message.type === 'final_answer'" v-html="renderMarkdown(message.content)"></div>
      <div class="message-code" v-else-if="message.type === 'action' || message.type === 'observation'">
        <div v-if="message.metadata?.tool" class="tool-badge">{{ message.metadata.tool }}</div>
        <div v-if="message.metadata?.error" class="error-badge">오류: {{ message.metadata.error }}</div>
        
        <!-- Tool Result 정보 표시 -->
        <div v-if="message.metadata?.tool_result" class="tool-result-info">
          <div class="tool-status" :class="{'success': message.metadata.tool_result.success, 'failure': !message.metadata.tool_result.success}"
               @click="toggleToolDetails">
            <span class="status-icon">{{ message.metadata.tool_result.success ? '✅' : '❌' }}</span>
            <span class="status-text">{{ message.metadata.tool_result.success ? '실행 성공' : '실행 실패' }}</span>
            <span class="toggle-icon">{{ showToolDetails ? '▼' : '▶' }}</span>
          </div>
          
          <div v-if="showToolDetails" class="tool-details">
            <div v-if="message.metadata.tool_input" class="tool-section">
              <div class="section-title">📥 입력 파라미터:</div>
              <pre class="tool-data"><code>{{ formatJson(message.metadata.tool_input) }}</code></pre>
            </div>
            
            <div v-if="message.metadata.tool_result.result" class="tool-section">
              <div class="section-title">📤 실행 결과:</div>
              <pre class="tool-data"><code>{{ formatJson(message.metadata.tool_result.result) }}</code></pre>
            </div>
            
            <div v-if="message.metadata.tool_result.error" class="tool-section">
              <div class="section-title">❌ 오류 내용:</div>
              <div class="error-text">{{ message.metadata.tool_result.error }}</div>
            </div>
            
            <div v-if="message.metadata.tool_result.metadata && Object.keys(message.metadata.tool_result.metadata).length > 0" class="tool-section">
              <div class="section-title">ℹ️ 메타데이터:</div>
              <pre class="tool-data"><code>{{ formatJson(message.metadata.tool_result.metadata) }}</code></pre>
            </div>
          </div>
        </div>
        
        <div class="observation-content">
          <div class="section-title">👁️ 관찰 결과:</div>
          <pre><code>{{ message.content }}</code></pre>
        </div>
      </div>
      <div class="message-error" v-else-if="message.type === 'error'">
        {{ message.content }}
        <div v-if="message.metadata?.message" class="error-details">
          <strong>상세:</strong> {{ message.metadata.message }}
        </div>
      </div>
      <div class="message-text" v-else>
        {{ message.content }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { Message } from '../types/Message'
import { getMessageIcon, getMessageTitle, formatTime, copyMessage } from '../utils/messageUtils'
import { renderMarkdown } from '../utils/markdownUtils'

interface Props {
  message: Message
}

defineProps<Props>()

// 접기/펼치기 상태
const showToolDetails = ref(false)

// 접기/펼치기 토글 함수
function toggleToolDetails() {
  showToolDetails.value = !showToolDetails.value
}

// JSON을 포맷팅하는 함수
function formatJson(data: any): string {
  if (data === null || data === undefined) {
    return String(data)
  }
  
  if (typeof data === 'string') {
    return data
  }
  
  try {
    return JSON.stringify(data, null, 2)
  } catch (error) {
    return String(data)
  }
}
</script>

<style scoped>
/* 메시지 카드 스타일 */
.message-card {
  border-radius: var(--border-radius);
  overflow: hidden;
  box-shadow: var(--shadow-md);
  transition: var(--transition);
  border: 2px solid;
  margin-bottom: 1rem;
}

.message-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
}

.message-thought:hover {
  box-shadow: 0 8px 25px rgba(59, 130, 246, 0.3);
}

.message-action:hover {
  box-shadow: 0 8px 25px rgba(245, 158, 11, 0.3);
}

.message-observation:hover {
  box-shadow: 0 8px 25px rgba(5, 150, 105, 0.3);
}

.message-final_answer:hover {
  box-shadow: 0 8px 25px rgba(124, 58, 237, 0.3);
}

.message-error:hover {
  box-shadow: 0 8px 25px rgba(220, 38, 38, 0.3);
}

.message-token:hover {
  box-shadow: 0 8px 25px rgba(100, 116, 139, 0.3);
}

.message-card .message-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  font-weight: 500;
}

.message-card .message-icon {
  font-size: 1.25rem;
}

.message-card .message-title {
  font-weight: 600;
  font-size: 0.95rem;
}

.message-card .message-timestamp {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-left: auto;
}

.message-card .copy-btn {
  background: linear-gradient(135deg, var(--primary-color) 0%, #1d4ed8 100%);
  color: white;
  border: 1px solid var(--primary-color);
  border-radius: 8px;
  padding: 0.4rem 0.75rem;
  cursor: pointer;
  transition: var(--transition);
  font-size: 0.85rem;
  font-weight: 500;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.2);
  position: relative;
  overflow: hidden;
}

.message-card .copy-btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
  transition: left 0.3s ease;
}

.message-card .copy-btn:hover {
  transform: scale(1.05) translateY(-1px);
  background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

.message-card .copy-btn:hover::before {
  left: 100%;
}

.message-card .copy-btn:active {
  transform: scale(0.98);
  box-shadow: 0 1px 3px rgba(37, 99, 235, 0.2);
}

.message-card .message-content {
  padding: 1.25rem;
  border-top: 1px solid var(--border-color);
}

/* 사고과정 메시지 */
.message-thought {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 100%);
  border-color: var(--primary-color);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

.message-thought .message-header {
  background: rgba(59, 130, 246, 0.1);
  color: var(--primary-color);
}

.message-thought .message-text {
  color: var(--primary-color);
  font-style: italic;
  font-size: 1.05rem;
  line-height: 1.6;
}

/* 액션 메시지 */
.message-action {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.1) 0%, rgba(245, 158, 11, 0.05) 100%);
  border-color: var(--warning-color);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.2);
}

.message-action .message-header {
  background: rgba(245, 158, 11, 0.1);
  color: var(--warning-color);
}

.message-action .tool-badge {
  background: var(--warning-color);
  color: white;
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: uppercase;
  margin-bottom: 0.75rem;
  display: inline-block;
}

/* 관찰 메시지 */
.message-observation {
  background: linear-gradient(135deg, rgba(5, 150, 105, 0.1) 0%, rgba(5, 150, 105, 0.05) 100%);
  border-color: var(--success-color);
  box-shadow: 0 4px 12px rgba(5, 150, 105, 0.2);
}

.message-observation .message-header {
  background: rgba(5, 150, 105, 0.1);
  color: var(--success-color);
}

.message-observation .error-badge {
  background: var(--error-color);
  color: white;
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
  margin-bottom: 0.75rem;
  display: inline-block;
}

/* 최종 답변 메시지 */
.message-final_answer {
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.1) 0%, rgba(124, 58, 237, 0.05) 100%);
  border-color: var(--secondary-color);
  box-shadow: 0 4px 12px rgba(124, 58, 237, 0.2);
}

.message-final_answer .message-header {
  background: rgba(124, 58, 237, 0.1);
  color: var(--secondary-color);
}

.message-final_answer .message-text {
  color: var(--secondary-color);
  font-size: 1.05rem;
  line-height: 1.7;
}

/* 오류 메시지 */
.message-error {
  background: linear-gradient(135deg, rgba(220, 38, 38, 0.1) 0%, rgba(220, 38, 38, 0.05) 100%);
  border-color: var(--error-color);
  box-shadow: 0 4px 12px rgba(220, 38, 38, 0.2);
}

.message-error .message-header {
  background: rgba(220, 38, 38, 0.1);
  color: var(--error-color);
}

.message-error .message-error {
  color: var(--error-color);
  font-weight: 500;
}

.message-error .error-details {
  margin-top: 0.75rem;
  padding: 0.75rem;
  background: rgba(220, 38, 38, 0.05);
  border-radius: 6px;
  font-size: 0.9rem;
}

/* 토큰 메시지 */
.message-token {
  background: var(--bg-secondary);
  border-color: var(--border-color);
  box-shadow: 0 4px 12px rgba(100, 116, 139, 0.2);
}

.message-token .message-header {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.message-token .message-text {
  color: var(--text-primary);
  font-size: 1rem;
  line-height: 1.7;
}

/* 시작 메시지 */
.message-start {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1) 0%, rgba(14, 165, 233, 0.05) 100%);
  border-color: #0ea5e9;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.2);
}

.message-start .message-header {
  background: rgba(14, 165, 233, 0.1);
  color: #0ea5e9;
}

.message-start .message-text {
  color: #0ea5e9;
  font-size: 1rem;
  line-height: 1.7;
  white-space: pre-wrap;
}

/* 종료 메시지 */
.message-end {
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.1) 0%, rgba(34, 197, 94, 0.05) 100%);
  border-color: #22c55e;
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.2);
}

.message-end .message-header {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}

.message-end .message-text {
  color: #22c55e;
  font-size: 1rem;
  line-height: 1.7;
}

/* 코드 스타일 */
.message-code pre {
  margin: 0;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 8px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 0.9rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
}

.message-code code {
  color: inherit;
  background: none;
  padding: 0;
  font-size: inherit;
}

/* Markdown rendered content */
.markdown-body {
  line-height: 1.75;
  color: var(--text-primary);
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3 {
  margin: 1rem 0 0.75rem;
  font-weight: 700;
}

.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  margin: 0.75rem 0 0.5rem;
  font-weight: 600;
}

.markdown-body p {
  margin: 0.75rem 0;
}

.markdown-body ul,
.markdown-body ol {
  padding-left: 1.25rem;
  margin: 0.75rem 0;
}

.markdown-body li + li {
  margin-top: 0.25rem;
}

.markdown-body a {
  color: #2563eb;
  text-decoration: underline;
}

.markdown-body blockquote {
  margin: 0.75rem 0;
  padding: 0.5rem 1rem;
  border-left: 4px solid #c7d2fe;
  background: #f8fafc;
  color: #334155;
}

.markdown-body pre code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.markdown-body code:not(pre code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
}

/* 텍스트 스타일 */
.message-text {
  line-height: 1.6;
}

.message-text strong {
  font-weight: 600;
}

.message-text em {
  font-style: italic;
}

.message-text code {
  background: rgba(0, 0, 0, 0.1);
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.9em;
}

/* Tool Result 스타일 */
.tool-result-info {
  margin: 1rem 0;
  padding: 1rem;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.02);
}

.tool-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
  transition: var(--transition);
  user-select: none;
}

.tool-status:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.tool-status.success {
  background: rgba(34, 197, 94, 0.1);
  color: #059669;
  border: 1px solid rgba(34, 197, 94, 0.2);
}

.tool-status.success:hover {
  background: rgba(34, 197, 94, 0.15);
}

.tool-status.failure {
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.tool-status.failure:hover {
  background: rgba(239, 68, 68, 0.15);
}

.status-icon {
  font-size: 1.1rem;
}

.status-text {
  font-weight: 600;
  flex: 1;
}

.toggle-icon {
  font-size: 0.9rem;
  transition: transform 0.2s ease;
  color: var(--text-secondary);
}

.tool-details {
  margin-top: 0.5rem;
  animation: slideDown 0.2s ease-out;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.tool-section {
  margin: 0.75rem 0;
}

.section-title {
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.tool-data {
  margin: 0;
  padding: 0.75rem;
  background: rgba(0, 0, 0, 0.04);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 6px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 0.85rem;
  line-height: 1.4;
  max-height: 300px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.tool-data code {
  color: var(--text-primary);
  background: none;
  padding: 0;
  font-size: inherit;
}

.error-text {
  padding: 0.75rem;
  background: rgba(239, 68, 68, 0.05);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 6px;
  color: #dc2626;
  font-weight: 500;
}

.observation-content {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
}

.observation-content .section-title {
  color: var(--success-color);
}
</style>
