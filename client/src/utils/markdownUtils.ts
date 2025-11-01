import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import taskLists from 'markdown-it-task-lists'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        const highlighted = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
        return `<pre class="hljs"><code>${highlighted}</code></pre>`
      } catch (e) {
        /* noop */
      }
    }
    const escaped: string = code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
    return `<pre class="hljs"><code>${escaped}</code></pre>`
  }
}).use(taskLists)

export function renderMarkdown(content: string): string {
  const unsafe = md.render(content || '')
  const sanitized = DOMPurify.sanitize(unsafe)
  
  // 테이블을 스크롤 가능한 wrapper로 감싸기
  const wrapped = sanitized.replace(
    /<table>/g,
    '<div class="table-wrapper"><table>'
  ).replace(
    /<\/table>/g,
    '</table></div>'
  )
  
  return wrapped
}
