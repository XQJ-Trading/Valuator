<template>
  <div class="formatted-text-viewer">
    <div class="text-content" v-html="formattedText"></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  text: string
}

const props = defineProps<Props>()

const formattedText = computed(() => {
  if (!props.text) return ''
  
  let formatted = escapeHtml(props.text)
  
  // Markdown 스타일 포맷팅
  // **bold**
  formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  
  // *italic*
  formatted = formatted.replace(/\*(.+?)\*/g, '<em>$1</em>')
  
  // `code`
  formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>')
  
  // ```code blocks```
  formatted = formatted.replace(/```(\w+)?\n([\s\S]*?)```/g, (match, lang, code) => {
    return `<pre class="code-block"><code class="language-${lang || 'text'}">${escapeHtml(code.trim())}</code></pre>`
  })
  
  // # Headers (먼저 처리)
  formatted = formatted.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  formatted = formatted.replace(/^## (.+)$/gm, '<h2>$1</h2>')
  formatted = formatted.replace(/^# (.+)$/gm, '<h1>$1</h1>')
  
  // Lists 처리 (줄 단위로)
  const lines = formatted.split('\n')
  const processedLines: string[] = []
  let inList = false
  let listType: 'ul' | 'ol' | null = null
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const bulletMatch = line.match(/^[-*] (.+)$/)
    const numberMatch = line.match(/^(\d+)\. (.+)$/)
    
    if (bulletMatch) {
      if (!inList || listType !== 'ul') {
        if (inList && listType === 'ol') {
          processedLines.push('</ol>')
        }
        processedLines.push('<ul>')
        inList = true
        listType = 'ul'
      }
      processedLines.push(`<li>${bulletMatch[1]}</li>`)
    } else if (numberMatch) {
      if (!inList || listType !== 'ol') {
        if (inList && listType === 'ul') {
          processedLines.push('</ul>')
        }
        processedLines.push('<ol>')
        inList = true
        listType = 'ol'
      }
      processedLines.push(`<li>${numberMatch[2]}</li>`)
    } else {
      if (inList) {
        processedLines.push(listType === 'ul' ? '</ul>' : '</ol>')
        inList = false
        listType = null
      }
      processedLines.push(line)
    }
  }
  
  if (inList) {
    processedLines.push(listType === 'ul' ? '</ul>' : '</ol>')
  }
  
  formatted = processedLines.join('\n')
  
  // Line breaks
  formatted = formatted.replace(/\n\n+/g, '</p><p>')
  formatted = formatted.replace(/\n/g, '<br>')
  
  // Wrap in paragraphs if needed
  if (!formatted.includes('<h1>') && !formatted.includes('<h2>') && !formatted.includes('<h3>') && !formatted.includes('<ul>') && !formatted.includes('<ol>')) {
    if (!formatted.startsWith('<p>')) {
      formatted = '<p>' + formatted
    }
    if (!formatted.endsWith('</p>')) {
      formatted = formatted + '</p>'
    }
  }
  
  return formatted
})

function escapeHtml(text: string): string {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}
</script>

<style scoped>
.formatted-text-viewer {
  width: 100%;
}

.text-content {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
  line-height: 1.8;
  color: var(--text-primary);
  font-size: 0.95rem;
}

.text-content :deep(p) {
  margin: 0.75rem 0;
}

.text-content :deep(h1) {
  font-size: 1.5rem;
  font-weight: 700;
  margin: 1.5rem 0 1rem;
  color: var(--text-primary);
  border-bottom: 2px solid var(--border-color);
  padding-bottom: 0.5rem;
}

.text-content :deep(h2) {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 1.25rem 0 0.75rem;
  color: var(--text-primary);
}

.text-content :deep(h3) {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 1rem 0 0.5rem;
  color: var(--text-primary);
}

.text-content :deep(strong) {
  font-weight: 600;
  color: var(--text-primary);
}

.text-content :deep(em) {
  font-style: italic;
}

.text-content :deep(code) {
  background: #f3f4f6;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 0.9em;
  color: #dc2626;
  border: 1px solid #e5e7eb;
}

.text-content :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 1rem;
  border-radius: var(--border-radius);
  overflow-x: auto;
  margin: 1rem 0;
  border: 1px solid #334155;
}

.text-content :deep(pre code) {
  background: transparent;
  padding: 0;
  border: none;
  color: inherit;
  font-size: 0.9rem;
  line-height: 1.6;
}

.text-content :deep(ul),
.text-content :deep(ol) {
  margin: 0.75rem 0;
  padding-left: 2rem;
}

.text-content :deep(li) {
  margin: 0.5rem 0;
}

.text-content :deep(blockquote) {
  border-left: 4px solid var(--primary-color);
  padding-left: 1rem;
  margin: 1rem 0;
  color: var(--text-secondary);
  font-style: italic;
}
</style>

