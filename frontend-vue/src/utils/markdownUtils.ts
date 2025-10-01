import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'

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
})

export function renderMarkdown(content: string): string {
  const unsafe = md.render(content || '')
  return DOMPurify.sanitize(unsafe)
}
