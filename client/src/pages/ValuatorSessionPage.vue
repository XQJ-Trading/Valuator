<template>
  <div class="valuator-page valuator-session-page">
    <div class="valuator-page-header">
      <router-link to="/sessions" class="valuator-link-back">← Sessions</router-link>
      <h1>Valuator Session</h1>
      <router-link :to="finalRoute" class="valuator-link-final">Final</router-link>
    </div>

    <section class="valuator-live-strip">
      <div class="valuator-live-strip-top">
        <div class="valuator-live-summary">
          <span class="valuator-live-status" :class="liveStatusClass">{{ liveStatusText }}</span>
          <span class="valuator-live-meta">{{ roundText }}</span>
          <span class="valuator-live-meta">Execution {{ executionCount }} / {{ totalLeafTaskCount }}</span>
          <span class="valuator-live-meta">Aggregation {{ aggregationCount }} / {{ totalLeafTaskCount }}</span>
          <span class="valuator-live-meta">Updated {{ lastUpdatedText }}</span>
        </div>
        <button class="valuator-refresh-btn" :disabled="manualRefreshing" @click="refreshSnapshotManually">
          {{ manualRefreshing ? 'Refreshing...' : 'Refresh now' }}
        </button>
      </div>

      <div class="valuator-live-updates-header">
        <h2>Step Updates</h2>
      </div>
      <p v-if="!latestLiveEvent" class="valuator-live-events-empty">
        Waiting for step updates...
      </p>
      <ul v-else class="valuator-live-event-list">
        <li class="valuator-live-event-item valuator-live-event-item-live">
          <span class="valuator-live-event-badge valuator-live-event-badge-live">LIVE</span>
          <span class="valuator-live-event-type">{{ latestLiveEvent.type }}</span>
          <span class="valuator-live-event-time">{{ formatEventTime(latestLiveEvent.at) }}</span>
          <p class="valuator-live-event-text">{{ latestLiveEvent.text }}</p>
        </li>
      </ul>
    </section>

    <div class="valuator-progress-bar">
      <div class="valuator-progress-fill" :style="{ width: `${progressPercent}%` }"></div>
    </div>

    <div v-if="loading" class="valuator-state">Loading snapshot...</div>
    <div v-else-if="error" class="valuator-state valuator-state-error">{{ error }}</div>
    <div v-else-if="!snapshot" class="valuator-state">{{ snapshotEmptyMessage }}</div>

    <div v-else class="valuator-session-layout">
      <ValuatorSidebar
        :query="snapshot.query"
        :final-route="finalRoute"
        :show-execution="showExecution"
        :show-aggregation="showAggregation"
        @update:showExecution="onShowExecutionUpdate"
        @update:showAggregation="onShowAggregationUpdate"
      />

      <section class="valuator-main-panel">
        <section class="valuator-final-inline-panel">
          <h2>Final Result</h2>
          <p v-if="!finalMarkdown" class="valuator-preview-empty">{{ finalPreviewMessage }}</p>
          <div
            v-else
            class="valuator-markdown valuator-final-markdown"
            v-html="finalMarkdownHtml"
          ></div>
        </section>

        <div class="valuator-subquery-list">
          <h2>Sub-queries</h2>
          <button
            v-for="group in subQueryGroups"
            :key="group.unit_id"
            class="valuator-subquery-item"
            :class="{ 'valuator-subquery-item-active': group.unit_id === selectedUnitId }"
            @click="selectedUnitId = group.unit_id"
          >
            <span class="valuator-subquery-id">Q{{ group.unit_id + 1 }}</span>
            <span class="valuator-subquery-label">{{ group.label }}</span>
            <span
              class="valuator-subquery-status"
              :class="`valuator-subquery-status-${subQueryStatus(group)}`"
            >
              {{ subQueryStatusText(group) }} {{ readyTaskCount(group) }}/{{ group.tasks.length }}
            </span>
          </button>
        </div>

        <div class="valuator-task-panel">
          <h2>Tasks</h2>
          <p class="valuator-root-task" v-if="rootTask">Root: {{ rootTask.id }}</p>

          <div v-if="!selectedGroup" class="valuator-state">Select a sub-query.</div>

          <div v-else class="valuator-task-list">
            <article v-for="task in selectedGroup.tasks" :key="task.id" class="valuator-task-card">
              <div class="valuator-task-card-header">
                <router-link
                  class="valuator-task-link"
                  :to="`/sessions/${sessionId}/tasks/${task.id}`"
                >
                  {{ task.id }}
                </router-link>
                <span
                  class="valuator-task-status"
                  :class="`valuator-task-status-${task.computed_status}`"
                >
                  {{ task.computed_status }}
                </span>
              </div>
              <p class="valuator-task-desc">{{ task.description }}</p>
              <p v-if="showExecution && task.tool" class="valuator-task-tool">
                tool: {{ task.tool.name }}
              </p>
            </article>
          </div>

          <div class="valuator-subquery-markdown-panel">
            <h3>Sub-query Markdown</h3>
            <p v-if="selectedUnitMarkdownLoading" class="valuator-preview-empty">Building markdown view...</p>
            <p v-else-if="!selectedUnitMarkdown" class="valuator-preview-empty">
              Select a sub-query or wait for execution results.
            </p>
            <div
              v-else
              class="valuator-markdown valuator-subquery-markdown"
              v-html="selectedUnitMarkdownHtml"
            ></div>
          </div>

          <div v-if="showAggregation && selectedGroup" class="valuator-aggregation-panel">
            <h3>Aggregation</h3>
            <p class="valuator-aggregation-meta">
              Reports {{ selectedAggregationReportCount }} / {{ selectedGroup.tasks.length }}
            </p>
            <p v-if="selectedAggregationReportTaskIds.length > 0" class="valuator-aggregation-reports">
              Report tasks: {{ selectedAggregationReportTaskIds.join(', ') }}
            </p>
            <p v-if="selectedAggregationReportCount === 0" class="valuator-aggregation-empty">
              No aggregation reports for this sub-query yet.
            </p>
          </div>

        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ValuatorApiClient } from '../api/ValuatorApiClient'
import ValuatorSidebar from '../components/valuator/ValuatorSidebar.vue'
import { useValuatorGraph } from '../composables/useValuatorGraph'
import { useValuatorSession } from '../composables/useValuatorSession'
import type { ValuatorSnapshot, ValuatorSubQueryGroup } from '../types/Valuator'
import { renderMarkdown } from '../utils/markdownUtils'

interface Props {
  sessionId: string
}

interface ValuatorLiveEvent {
  id: string
  type: string
  text: string
  at: number
}

interface StreamEventPayload {
  type?: string
  content?: string
  message?: string
  query?: string
  tool?: string
  stage?: string
  round?: number
}

type StreamStatus = 'idle' | 'connecting' | 'live' | 'closed' | 'error'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
const SNAPSHOT_POLL_INTERVAL_MS = 2500
const LIVE_EVENT_MAX_SIZE = 40
const valuatorApiClient = new ValuatorApiClient()

const props = defineProps<Props>()

const { snapshot, loading, error, fetchSnapshot } = useValuatorSession()
const { subQueryGroups, rootTask } = useValuatorGraph(snapshot)

const selectedUnitId = ref<number | null>(null)
const showExecution = ref(true)
const showAggregation = ref(true)
const manualRefreshing = ref(false)
const streamStatus = ref<StreamStatus>('idle')
const liveEvents = ref<ValuatorLiveEvent[]>([])
const lastUpdatedAt = ref<number | null>(null)
const finalMarkdown = ref('')
const terminalSyncStarted = ref(false)
const selectedUnitMarkdown = ref('')
const selectedUnitMarkdownLoading = ref(false)
const selectedUnitMarkdownKey = ref('')

const sessionId = computed(() => props.sessionId)
const finalRoute = computed(() => `/sessions/${sessionId.value}/final`)
const totalLeafTaskCount = computed(
  () => snapshot.value?.plan.tasks.filter((task) => task.task_type === 'leaf').length || 0
)
const executionCount = computed(() => snapshot.value?.execution.artifacts.length || 0)
const aggregationCount = computed(() => snapshot.value?.aggregation.reports.length || 0)
const progressPercent = computed(() => {
  if (totalLeafTaskCount.value === 0) {
    return 0
  }
  return Math.min(100, Math.round((executionCount.value / totalLeafTaskCount.value) * 100))
})
const roundText = computed(() => {
  if (!snapshot.value?.round) {
    return 'Round -'
  }
  return `Round ${snapshot.value.round}`
})
const lastUpdatedText = computed(() => {
  if (!lastUpdatedAt.value) {
    return '-'
  }
  return new Date(lastUpdatedAt.value).toLocaleTimeString('ko-KR')
})
const liveStatusText = computed(() => {
  if (streamStatus.value === 'live') {
    return 'LIVE'
  }
  if (streamStatus.value === 'connecting') {
    return 'CONNECTING'
  }
  if (streamStatus.value === 'error') {
    return 'STREAM ERROR'
  }
  if (isSnapshotTerminal(snapshot.value)) {
    return 'COMPLETED'
  }
  return 'IDLE'
})
const liveStatusClass = computed(() => {
  if (streamStatus.value === 'live') {
    return 'valuator-live-status-live'
  }
  if (streamStatus.value === 'connecting') {
    return 'valuator-live-status-connecting'
  }
  if (streamStatus.value === 'error') {
    return 'valuator-live-status-error'
  }
  if (isSnapshotTerminal(snapshot.value)) {
    return 'valuator-live-status-completed'
  }
  return 'valuator-live-status-idle'
})
const snapshotEmptyMessage = computed(() => {
  if (streamStatus.value === 'live' || streamStatus.value === 'connecting') {
    return 'Session is running. Waiting for plan/task artifacts...'
  }
  return 'Snapshot not found.'
})
const latestLiveEvent = computed(() => {
  const total = liveEvents.value.length
  return total > 0 ? liveEvents.value[total - 1] : null
})
const finalMarkdownHtml = computed(() => renderMarkdown(finalMarkdown.value))
const selectedUnitMarkdownHtml = computed(() => renderMarkdown(selectedUnitMarkdown.value))
const finalPreviewMessage = computed(() => {
  if (streamStatus.value === 'live' || streamStatus.value === 'connecting') {
    return 'Generating final result...'
  }
  if (isSnapshotTerminal(snapshot.value)) {
    return 'Final output is being synchronized...'
  }
  return 'Final result not available yet.'
})

const selectedGroup = computed(() => {
  if (selectedUnitId.value === null) {
    return null
  }
  return subQueryGroups.value.find((group) => group.unit_id === selectedUnitId.value) || null
})
const selectedAggregationReportTaskIds = computed(() => {
  const current = snapshot.value
  const group = selectedGroup.value
  if (!current || !group) {
    return []
  }
  const taskIds = new Set(group.tasks.map((task) => task.id))
  return (current.aggregation.reports || [])
    .filter((report) => taskIds.has(report.task_id))
    .map((report) => report.task_id)
    .sort()
})
const selectedAggregationReportCount = computed(() => selectedAggregationReportTaskIds.value.length)

let streamSource: EventSource | null = null
let snapshotPollTimer: number | null = null
let selectedUnitRequestId = 0
let finalSyncRequestId = 0

watch(
  () => props.sessionId,
  (nextSessionId) => {
    void initializeSession(nextSessionId)
  },
  { immediate: true }
)

watch(
  subQueryGroups,
  (groups) => {
    if (groups.length === 0) {
      selectedUnitId.value = null
      return
    }
    if (selectedUnitId.value === null) {
      selectedUnitId.value = groups[0].unit_id
      return
    }
    const exists = groups.some((group) => group.unit_id === selectedUnitId.value)
    if (!exists) {
      selectedUnitId.value = groups[0].unit_id
    }
  },
  { immediate: true }
)

watch(
  () => [
    selectedUnitId.value,
    snapshot.value?.round || 0,
    snapshot.value?.execution.artifacts.length || 0,
    snapshot.value?.aggregation.reports.length || 0,
    snapshot.value?.review.round || 0,
    snapshot.value?.review.status || '',
    snapshot.value?.review.actions.length || 0
  ],
  () => {
    void syncSelectedUnitMarkdown()
  },
  { immediate: true }
)

function onShowExecutionUpdate(value: boolean) {
  showExecution.value = value
}

function onShowAggregationUpdate(value: boolean) {
  showAggregation.value = value
}

function readyTaskCount(group: ValuatorSubQueryGroup): number {
  return group.tasks.filter((task) => task.computed_status === 'ready').length
}

function pendingTaskCount(group: ValuatorSubQueryGroup): number {
  return group.tasks.filter((task) => task.computed_status === 'pending').length
}

function subQueryStatus(group: ValuatorSubQueryGroup): 'ready' | 'pending' {
  if (pendingTaskCount(group) > 0) {
    return 'pending'
  }
  return 'ready'
}

function subQueryStatusText(group: ValuatorSubQueryGroup): string {
  const status = subQueryStatus(group)
  if (status === 'pending') {
    return 'PENDING'
  }
  return 'READY'
}

async function initializeSession(nextSessionId: string) {
  stopLiveStream()
  stopSnapshotPolling()
  streamStatus.value = 'idle'
  liveEvents.value = []
  lastUpdatedAt.value = null
  finalMarkdown.value = ''
  terminalSyncStarted.value = false
  selectedUnitRequestId += 1
  finalSyncRequestId += 1
  selectedUnitMarkdown.value = ''
  selectedUnitMarkdownKey.value = ''

  await fetchSnapshot(nextSessionId, {
    allowNotFound: true,
    keepSnapshotOnError: true
  })
  if (snapshot.value) {
    lastUpdatedAt.value = Date.now()
    void syncSelectedUnitMarkdown()
  }
  await syncFinalDocument({ allowNotFound: true, retries: 0 })

  startSnapshotPolling()
  startLiveStream(nextSessionId)
}

function startSnapshotPolling() {
  stopSnapshotPolling()
  snapshotPollTimer = window.setInterval(() => {
    void refreshSnapshot({ silent: true })
  }, SNAPSHOT_POLL_INTERVAL_MS)
}

function stopSnapshotPolling() {
  if (snapshotPollTimer !== null) {
    window.clearInterval(snapshotPollTimer)
    snapshotPollTimer = null
  }
}

function startLiveStream(targetSessionId: string) {
  stopLiveStream()
  streamStatus.value = 'connecting'
  const source = new EventSource(`${API_BASE}/api/v1/sessions/${targetSessionId}/stream`)
  streamSource = source

  source.onopen = () => {
    if (streamSource !== source) {
      return
    }
    streamStatus.value = 'live'
    pushLiveEvent('connected', 'Stream connected.')
  }

  source.onmessage = (event) => {
    if (streamSource !== source) {
      return
    }
    const payload = parseStreamEventPayload(event.data)
    if (!payload) {
      return
    }

    const type = payload.type || 'message'
    pushLiveEvent(type, toStreamEventText(payload))
    void refreshSnapshot({ silent: true })
    if (type === 'final_answer') {
      const content = String(payload.content || '').trim()
      if (content) {
        finalMarkdown.value = content
      }
    }

    if (type === 'end') {
      streamStatus.value = 'closed'
      stopLiveStream()
      markTerminalSyncAndRun()
    } else if (type === 'error') {
      streamStatus.value = 'error'
      stopLiveStream()
    }
  }

  source.onerror = () => {
    if (streamSource !== source) {
      return
    }
    if (streamStatus.value === 'connecting') {
      streamStatus.value = isSnapshotTerminal(snapshot.value) ? 'closed' : 'idle'
    } else if (streamStatus.value === 'live') {
      streamStatus.value = isSnapshotTerminal(snapshot.value) ? 'closed' : 'error'
    }
    stopLiveStream()
  }
}

function stopLiveStream() {
  if (!streamSource) {
    return
  }
  streamSource.close()
  streamSource = null
}

async function refreshSnapshot(options: { silent?: boolean } = {}) {
  const ok = await fetchSnapshot(sessionId.value, {
    silent: options.silent,
    allowNotFound: true,
    keepSnapshotOnError: true
  })
  if (ok) {
    lastUpdatedAt.value = Date.now()
    void syncSelectedUnitMarkdown()
    if (!finalMarkdown.value) {
      void syncFinalDocument({ allowNotFound: true, retries: 0 })
    }
  }
  if (isSnapshotTerminal(snapshot.value)) {
    markTerminalSyncAndRun()
  }
}

async function refreshSnapshotManually() {
  manualRefreshing.value = true
  try {
    await refreshSnapshot({ silent: true })
  } finally {
    manualRefreshing.value = false
  }
}

function pushLiveEvent(type: string, text: string) {
  const nextEvent: ValuatorLiveEvent = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    type,
    text,
    at: Date.now()
  }
  const next = [...liveEvents.value, nextEvent]
  liveEvents.value = next.slice(-LIVE_EVENT_MAX_SIZE)
}

function parseStreamEventPayload(raw: string): StreamEventPayload | null {
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') {
      return null
    }
    return parsed as StreamEventPayload
  } catch {
    return null
  }
}

function toStreamEventText(payload: StreamEventPayload): string {
  const stage = payload.stage ? `[${payload.stage}] ` : ''
  const round = typeof payload.round === 'number' ? `(round ${payload.round}) ` : ''
  const body =
    payload.message?.trim() ||
    payload.content?.trim() ||
    payload.query?.trim() ||
    (payload.tool ? `tool: ${payload.tool}` : '')

  const raw = `${stage}${round}${body || '(empty)'}`.trim()
  return raw.length > 180 ? `${raw.slice(0, 180)}...` : raw
}

function formatEventTime(value: number): string {
  return new Date(value).toLocaleTimeString('ko-KR')
}

function isSnapshotTerminal(current: ValuatorSnapshot | null): boolean {
  if (!current) {
    return false
  }
  const reviewStatus = String(current.review.status || '').toLowerCase()
  if (reviewStatus === 'pass') {
    return true
  }
  const snapshotStatus = String(current.status || '').toLowerCase()
  return snapshotStatus === 'completed' || snapshotStatus === 'failed'
}

function markTerminalSyncAndRun() {
  if (terminalSyncStarted.value) {
    return
  }
  terminalSyncStarted.value = true
  stopSnapshotPolling()
  void syncSnapshotToStable(8)
  void syncSelectedUnitMarkdown()
  void syncFinalDocument({ allowNotFound: true, retries: 12 })
}

async function syncSnapshotToStable(maxAttempts: number) {
  let lastFingerprint = ''
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const ok = await fetchSnapshot(sessionId.value, {
      silent: true,
      allowNotFound: true,
      keepSnapshotOnError: true
    })
    if (ok) {
      lastUpdatedAt.value = Date.now()
      void syncSelectedUnitMarkdown()
      const current = snapshot.value
      const nextFingerprint = current
        ? [
            current.round || 0,
            current.execution.artifacts.length,
            current.aggregation.reports.length,
            current.review.status,
            current.review.actions.length
          ].join(':')
        : ''
      if (nextFingerprint && nextFingerprint === lastFingerprint) {
        return
      }
      lastFingerprint = nextFingerprint
    }
    await delay(450)
  }
}

async function syncSelectedUnitMarkdown() {
  const group = selectedGroup.value
  const current = snapshot.value
  if (!group || !current) {
    selectedUnitMarkdown.value = ''
    selectedUnitMarkdownKey.value = ''
    selectedUnitMarkdownLoading.value = false
    return
  }

  const taskIds = group.tasks.map((task) => task.id).join(',')
  const nextKey = [
    sessionId.value,
    selectedUnitId.value ?? -1,
    current.round || 0,
    current.execution.artifacts.length,
    current.aggregation.reports.length,
    current.review?.round || 0,
    current.review?.status || '',
    current.review?.actions?.length || 0,
    taskIds
  ].join(':')
  if (selectedUnitMarkdownKey.value === nextKey) {
    return
  }
  selectedUnitMarkdownKey.value = nextKey

  const requestId = ++selectedUnitRequestId
  selectedUnitMarkdownLoading.value = true
  try {
    const rows = await Promise.all(
      group.tasks.map(async (task) => {
        try {
          const detail = await valuatorApiClient.getTaskDetail(sessionId.value, task.id)
          return {
            taskId: task.id,
            description: task.description,
            executionMarkdown: detail.execution_markdown || '',
            aggregationMarkdown: detail.aggregation_markdown || ''
          }
        } catch (error) {
          if (getErrorStatus(error) !== 404) {
            console.warn(`Failed to fetch task detail for ${task.id}:`, error)
          }
          return {
            taskId: task.id,
            description: task.description,
            executionMarkdown: '',
            aggregationMarkdown: ''
          }
        }
      })
    )
    if (requestId !== selectedUnitRequestId) {
      return
    }
    selectedUnitMarkdown.value = buildSubQueryMarkdown(group, rows)
  } finally {
    if (requestId === selectedUnitRequestId) {
      selectedUnitMarkdownLoading.value = false
    }
  }
}

function buildSubQueryMarkdown(
  group: ValuatorSubQueryGroup,
  rows: Array<{
    taskId: string
    description: string
    executionMarkdown: string
    aggregationMarkdown: string
  }>
): string {
  const lines: string[] = [`# Q${group.unit_id + 1}`, '', group.label, '']
  for (const row of rows) {
    lines.push(`## ${row.taskId}`)
    lines.push(row.description || '(no description)')
    lines.push('')
    if (row.executionMarkdown.trim()) {
      lines.push('### Execution')
      lines.push(row.executionMarkdown.trim())
      lines.push('')
    }
    if (row.aggregationMarkdown.trim()) {
      lines.push('### Aggregation')
      lines.push(row.aggregationMarkdown.trim())
      lines.push('')
    }
    if (!row.executionMarkdown.trim() && !row.aggregationMarkdown.trim()) {
      lines.push('- (no artifacts yet)')
      lines.push('')
    }
  }
  return lines.join('\n').trim()
}

async function syncFinalDocument(options: { allowNotFound?: boolean; retries?: number }) {
  const requestId = ++finalSyncRequestId
  const targetSessionId = sessionId.value
  const retries = options.retries || 0
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const finalDoc = await valuatorApiClient.getFinal(targetSessionId)
      if (requestId !== finalSyncRequestId || targetSessionId !== sessionId.value) {
        return
      }
      const markdown = String(finalDoc.markdown || '').trim()
      if (markdown) {
        finalMarkdown.value = markdown
      }
      return
    } catch (error) {
      if (requestId !== finalSyncRequestId || targetSessionId !== sessionId.value) {
        return
      }
      const status = getErrorStatus(error)
      if (options.allowNotFound && status === 404 && attempt < retries) {
        await delay(600)
        continue
      }
      if (!(options.allowNotFound && status === 404)) {
        console.warn('Failed to sync final result:', error)
      }
      return
    }
  }
}

function getErrorStatus(error: unknown): number | null {
  if (!(error instanceof Error)) {
    return null
  }
  if (!('status' in error)) {
    return null
  }
  const raw = (error as Error & { status?: unknown }).status
  return typeof raw === 'number' ? raw : null
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

onBeforeUnmount(() => {
  stopLiveStream()
  stopSnapshotPolling()
})
</script>

<style scoped>
.valuator-page {
  min-height: calc(100vh - 60px);
  max-width: 1280px;
  margin: 0 auto;
  padding: 1rem;
}

.valuator-page-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.valuator-page-header h1 {
  margin: 0;
  flex: 1;
  font-size: 1.35rem;
}

.valuator-link-back,
.valuator-link-final {
  text-decoration: none;
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 0.4rem 0.65rem;
  font-size: 0.85rem;
  font-weight: 600;
}

.valuator-live-strip {
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  background: var(--bg-secondary);
  margin-bottom: 0.6rem;
  padding: 0.6rem 0.75rem;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.75rem;
}

.valuator-live-strip-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.valuator-live-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.valuator-live-status {
  font-size: 0.72rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 0.18rem 0.55rem;
  letter-spacing: 0.02em;
}

.valuator-live-status-live {
  background: rgba(5, 150, 105, 0.14);
  color: #047857;
}

.valuator-live-status-connecting {
  background: rgba(2, 132, 199, 0.14);
  color: #0369a1;
}

.valuator-live-status-completed {
  background: rgba(37, 99, 235, 0.14);
  color: #1d4ed8;
}

.valuator-live-status-error {
  background: rgba(220, 38, 38, 0.14);
  color: #b91c1c;
}

.valuator-live-status-idle {
  background: rgba(100, 116, 139, 0.14);
  color: #475569;
}

.valuator-live-meta {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.valuator-refresh-btn {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: white;
  color: var(--text-primary);
  padding: 0.35rem 0.65rem;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.valuator-refresh-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.valuator-live-updates-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
}

.valuator-live-updates-header h2 {
  margin: 0;
  font-size: 0.95rem;
}

.valuator-progress-bar {
  width: 100%;
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: #e2e8f0;
  margin-bottom: 1rem;
}

.valuator-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0284c7 0%, #2563eb 55%, #16a34a 100%);
  transition: width 220ms ease-out;
}

.valuator-session-layout {
  display: grid;
  grid-template-columns: minmax(240px, 300px) 1fr;
  gap: 1rem;
}

.valuator-main-panel {
  display: grid;
  grid-template-columns: minmax(220px, 320px) 1fr;
  gap: 1rem;
}

.valuator-final-inline-panel {
  grid-column: 1 / -1;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  background: var(--bg-secondary);
  padding: 1rem;
  min-height: 280px;
}

.valuator-final-inline-panel h2 {
  margin: 0 0 0.55rem;
  font-size: 1.05rem;
}

.valuator-subquery-list,
.valuator-task-panel {
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  border-radius: var(--border-radius);
  padding: 0.9rem;
}

.valuator-subquery-list h2,
.valuator-task-panel h2 {
  margin: 0 0 0.75rem;
  font-size: 1rem;
}

.valuator-subquery-item {
  width: 100%;
  border: 1px solid var(--border-color);
  background: white;
  border-radius: 8px;
  text-align: left;
  padding: 0.55rem 0.65rem;
  margin-bottom: 0.5rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.valuator-subquery-item-active {
  border-color: var(--primary-color);
}

.valuator-subquery-id {
  display: inline-block;
  margin-right: 0.4rem;
  font-weight: 700;
  color: var(--text-secondary);
}

.valuator-subquery-label {
  flex: 1;
  color: var(--text-primary);
  line-height: 1.35;
}

.valuator-subquery-status {
  font-size: 0.68rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 0.14rem 0.45rem;
  letter-spacing: 0.01em;
}

.valuator-subquery-status-ready {
  background: rgba(5, 150, 105, 0.13);
  color: #047857;
}

.valuator-subquery-status-pending {
  background: rgba(217, 119, 6, 0.15);
  color: #b45309;
}

.valuator-task-list {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.valuator-task-card {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: white;
  padding: 0.7rem;
}

.valuator-task-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
}

.valuator-task-link {
  color: var(--primary-color);
  font-weight: 700;
  text-decoration: none;
}

.valuator-task-status {
  font-size: 0.75rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 0.15rem 0.5rem;
  text-transform: uppercase;
}

.valuator-task-status-ready {
  background: rgba(5, 150, 105, 0.13);
  color: #047857;
}

.valuator-task-status-pending {
  background: rgba(217, 119, 6, 0.14);
  color: #b45309;
}

.valuator-task-desc {
  margin: 0.5rem 0 0;
  line-height: 1.4;
  color: var(--text-primary);
}

.valuator-task-tool,
.valuator-root-task {
  margin: 0.5rem 0 0;
  font-size: 0.82rem;
  color: var(--text-secondary);
}

.valuator-aggregation-panel {
  margin-top: 1rem;
  border-top: 1px solid var(--border-color);
  padding-top: 0.75rem;
}

.valuator-aggregation-panel h3 {
  margin: 0 0 0.45rem;
  font-size: 0.95rem;
}

.valuator-live-events-empty {
  margin: 0;
  font-size: 0.86rem;
  color: var(--text-secondary);
}

.valuator-live-event-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.valuator-live-event-item {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: white;
  padding: 0.5rem 0.6rem;
}

.valuator-live-event-item-live {
  border-color: rgba(5, 150, 105, 0.35);
}

.valuator-live-event-badge {
  display: inline-block;
  font-size: 0.68rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 0.12rem 0.42rem;
  margin-right: 0.35rem;
}

.valuator-live-event-badge-live {
  background: rgba(5, 150, 105, 0.14);
  color: #047857;
}

.valuator-live-event-type {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  color: #1e40af;
  background: rgba(37, 99, 235, 0.12);
  border-radius: 999px;
  padding: 0.14rem 0.45rem;
  margin-right: 0.35rem;
}

.valuator-live-event-time {
  font-size: 0.76rem;
  color: var(--text-secondary);
}

.valuator-live-event-text {
  margin: 0.35rem 0 0;
  font-size: 0.86rem;
  line-height: 1.4;
  color: var(--text-primary);
}

.valuator-subquery-markdown-panel {
  margin-top: 1rem;
  border-top: 1px solid var(--border-color);
  padding-top: 0.75rem;
}

.valuator-subquery-markdown-panel h3 {
  margin: 0 0 0.45rem;
  font-size: 0.95rem;
}

.valuator-preview-empty {
  margin: 0;
  font-size: 0.86rem;
  color: var(--text-secondary);
}

.valuator-markdown {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: white;
  padding: 0.85rem;
  overflow-x: auto;
}

.valuator-final-markdown {
  min-height: 220px;
  max-height: 560px;
  overflow-y: auto;
}

.valuator-subquery-markdown {
  max-height: 360px;
  overflow-y: auto;
}

.valuator-aggregation-empty {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.88rem;
}

.valuator-aggregation-meta {
  margin: 0 0 0.45rem;
  color: var(--text-secondary);
  font-size: 0.82rem;
}

.valuator-aggregation-reports {
  margin: 0 0 0.5rem;
  color: var(--text-secondary);
  font-size: 0.78rem;
}

.valuator-state {
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  border-radius: var(--border-radius);
  padding: 1rem;
}

.valuator-state-error {
  color: var(--error-color);
}

@media (max-width: 1080px) {
  .valuator-session-layout,
  .valuator-main-panel {
    grid-template-columns: 1fr;
  }

  .valuator-live-strip-top {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
