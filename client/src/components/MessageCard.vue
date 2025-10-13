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
      <div class="message-subtask-result" v-else-if="message.type === 'subtask_result'">
        <div class="subtask-badge">📋 서브태스크 결과</div>
        <div class="subtask-content markdown-body" v-html="renderMarkdown(message.content)"></div>
        <div v-if="message.metadata?.source_type" class="subtask-source">
          출처: {{ getMessageTitle(message.metadata.source_type as any) }}
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
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  font-weight: 500;
}

.message-card .message-icon {
  font-size: 1.1rem;
}

.message-card .message-title {
  font-weight: 600;
  font-size: 0.9rem;
}

.message-card .message-timestamp {
  font-size: 0.75rem;
  color: var(--text-secondary);
  flex: 1;
}

.message-card .copy-btn {
  background: linear-gradient(135deg, var(--primary-color) 0%, #1d4ed8 100%);
  color: white;
  border: 1px solid var(--primary-color);
  border-radius: 6px;
  padding: 0.3rem 0.5rem;
  cursor: pointer;
  transition: var(--transition);
  font-size: 0.8rem;
  font-weight: 500;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.2);
  position: relative;
  overflow: hidden;
  margin-left: auto;
  flex-shrink: 0;
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
  padding: 1rem;
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
  font-size: 0.95rem;
  line-height: 1.5;
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
  color: var(--text-primary);
  font-size: 0.95rem;
  line-height: 1.6;
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
  padding: 0.75rem;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 6px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 0.8rem;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
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

/* 테이블 컨테이너 래퍼 */
.markdown-body :deep(.table-wrapper) {
  overflow-x: auto;
  margin: 1rem 0;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  min-width: 600px;
  border: 2px solid #d1d5db !important;
  border-radius: 8px;
  overflow: hidden;
  box-sizing: border-box;
  font-size: 0.85rem;
  background: white;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #d1d5db !important;
  padding: 0.6rem 0.8rem;
  text-align: left;
  vertical-align: top;
  box-sizing: border-box;
  position: relative;
}

.markdown-body :deep(th:first-child),
.markdown-body :deep(td:first-child) {
  text-align: left;
  white-space: nowrap;
  font-weight: 600;
  min-width: 120px;
  max-width: 150px;
  position: sticky;
  left: 0;
  background: inherit !important;
  z-index: 2;
  box-shadow: 2px 0 5px -2px rgba(0, 0, 0, 0.1);
}

.markdown-body :deep(th:not(:first-child)),
.markdown-body :deep(td:not(:first-child)) {
  min-width: 150px;
  max-width: 250px;
  word-wrap: break-word;
  hyphens: auto;
  line-height: 1.3;
  white-space: normal;
}

.markdown-body :deep(td:not(:first-child)) {
  text-align: left;
}

/* 긴 텍스트 처리 */
.markdown-body :deep(td) {
  overflow: hidden;
  text-overflow: ellipsis;
  display: table-cell;
}

.markdown-body :deep(td:hover) {
  overflow: visible;
  white-space: normal;
  z-index: 10;
  position: relative;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  background: white !important;
  max-width: none !important;
}

/* 숫자가 포함된 열 스타일링 */
.markdown-body :deep(td:nth-child(n+2)) {
  font-variant-numeric: tabular-nums;
}

.markdown-body :deep(th) {
  background: #f8fafc !important;
  font-weight: 600;
  color: #1f2937;
  border-bottom: 2px solid #d1d5db !important;
}

.markdown-body :deep(td) {
  background: #ffffff !important;
}

.markdown-body :deep(tbody tr:nth-child(even) td) {
  background: #f9fafb !important;
}

.markdown-body :deep(tbody tr:hover td) {
  background: rgba(59, 130, 246, 0.05) !important;
}

.markdown-body :deep(table caption) {
  margin-bottom: 0.5rem;
  font-weight: 600;
  color: #1f2937;
}

/* 텍스트 스타일 */
.message-text {
  line-height: 1.6;
  font-size: 1rem;
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

/* 서브태스크 결과 메시지 */
.message-subtask-result {
  background: linear-gradient(135deg, rgba(168, 85, 247, 0.1) 0%, rgba(168, 85, 247, 0.05) 100%);
  border-color: #a855f7;
  box-shadow: 0 4px 12px rgba(168, 85, 247, 0.2);
}

.message-subtask-result .message-header {
  background: rgba(168, 85, 247, 0.1);
  color: #a855f7;
}

.message-subtask-result:hover {
  box-shadow: 0 8px 25px rgba(168, 85, 247, 0.3);
}

.message-subtask-result .subtask-badge {
  background: linear-gradient(135deg, #a855f7 0%, #9333ea 100%);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 20px;
  font-size: 0.85rem;
  font-weight: 600;
  text-align: center;
  margin-bottom: 1rem;
  display: inline-block;
  box-shadow: 0 2px 8px rgba(168, 85, 247, 0.3);
}

.message-subtask-result .subtask-content {
  font-size: 1rem;
  line-height: 1.6;
  padding: 0.75rem;
  background: rgba(168, 85, 247, 0.05);
  border-radius: 8px;
  border-left: 4px solid #a855f7;
  margin-bottom: 0.75rem;
}

.message-subtask-result .subtask-content :deep(*) {
  color: var(--text-primary) !important;
}

.message-subtask-result .subtask-source {
  font-size: 0.85rem;
  color: var(--text-secondary);
  font-style: italic;
  padding: 0.5rem 0.75rem;
  background: rgba(168, 85, 247, 0.03);
  border-radius: 6px;
  border: 1px solid rgba(168, 85, 247, 0.1);
}

/* 반응형 디자인 */
@media (max-width: 768px) {
  .message-card .message-header {
    padding: 0.6rem 0.85rem;
    gap: 0.4rem;
  }
  
  .message-card .message-icon {
    font-size: 1rem;
  }
  
  .message-card .message-title {
    font-size: 0.85rem;
  }
  
  .message-card .message-timestamp {
    font-size: 0.7rem;
  }
  
  .message-card .copy-btn {
    padding: 0.25rem 0.45rem;
    font-size: 0.75rem;
  }
  
  .message-card .message-content {
    padding: 0.85rem;
  }
  
  .message-text {
    font-size: 0.9rem;
    line-height: 1.5;
  }
  
  .message-thought .message-text,
  .message-final_answer .message-text {
    font-size: 0.85rem;
    line-height: 1.5;
  }
  
  .message-code pre {
    padding: 0.6rem;
    font-size: 0.75rem;
    max-height: 250px;
  }
  
  .tool-result-info {
    padding: 0.75rem;
  }
  
  .tool-data {
    padding: 0.6rem;
    font-size: 0.8rem;
    max-height: 200px;
  }
  
  .section-title {
    font-size: 0.85rem;
  }
  
  .markdown-body {
    font-size: 0.9rem;
    line-height: 1.6;
  }
  
  .markdown-body h1,
  .markdown-body h2,
  .markdown-body h3 {
    margin: 0.75rem 0 0.5rem;
  }
  
  .markdown-body p {
    margin: 0.6rem 0;
  }
  
  .markdown-body :deep(table) {
    font-size: 0.8rem;
    min-width: 500px;
  }
  
  .markdown-body :deep(th),
  .markdown-body :deep(td) {
    padding: 0.5rem 0.6rem;
  }
}

@media (max-width: 480px) {
  .message-card {
    margin-bottom: 0.85rem;
  }
  
  .message-card .message-header {
    padding: 0.5rem 0.7rem;
    gap: 0.3rem;
    flex-wrap: wrap;
  }
  
  .message-card .message-icon {
    font-size: 0.9rem;
  }
  
  .message-card .message-title {
    font-size: 0.8rem;
  }
  
  .message-card .message-timestamp {
    font-size: 0.65rem;
    width: 100%;
    margin-left: 0;
    margin-top: 0.2rem;
  }
  
  .message-card .copy-btn {
    padding: 0.2rem 0.35rem;
    font-size: 0.7rem;
  }
  
  .message-card .message-content {
    padding: 0.7rem;
  }
  
  .message-text {
    font-size: 0.85rem;
    line-height: 1.4;
  }
  
  .message-thought .message-text,
  .message-final_answer .message-text {
    font-size: 0.8rem;
    line-height: 1.4;
  }
  
  .message-code pre {
    padding: 0.5rem;
    font-size: 0.7rem;
    max-height: 200px;
  }
  
  .tool-result-info {
    padding: 0.6rem;
  }
  
  .tool-status {
    padding: 0.4rem 0.6rem;
    font-size: 0.85rem;
  }
  
  .tool-data {
    padding: 0.5rem;
    font-size: 0.75rem;
    max-height: 150px;
  }
  
  .section-title {
    font-size: 0.8rem;
  }
  
  .markdown-body {
    font-size: 0.85rem;
    line-height: 1.5;
  }
  
  .markdown-body :deep(table) {
    font-size: 0.75rem;
    min-width: 400px;
  }
  
  .markdown-body :deep(th),
  .markdown-body :deep(td) {
    padding: 0.4rem 0.5rem;
  }
  
  .markdown-body :deep(th:first-child),
  .markdown-body :deep(td:first-child) {
    min-width: 100px;
    max-width: 120px;
  }
  
  .error-details {
    padding: 0.6rem;
    font-size: 0.85rem;
  }
  
  .subtask-badge {
    font-size: 0.8rem;
    padding: 0.4rem 0.8rem;
  }
  
  .subtask-content {
    padding: 0.6rem;
    font-size: 0.9rem;
  }
  
  .subtask-source {
    font-size: 0.8rem;
    padding: 0.4rem 0.6rem;
  }
}
</style>
