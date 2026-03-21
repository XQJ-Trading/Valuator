# Fix: Tasks를 트리 구조로 표시 + Aggregation 카운트 수정

## Context

Plan(decomposition.json)의 태스크 그래프는 leaf → merge → root 트리 구조다.
현재 UI는 `task_type === 'leaf'`만 필터링하여:
1. Tasks 패널에 merge 태스크 누락 (10개 중 6개만 표시)
2. Aggregation 카운트가 leaf report만 집계 (백엔드는 leaf+merge 모두 report 생성)
3. 상단 live strip `Aggregation X / totalLeafTaskCount` 분모 불일치

트리 구조로 렌더링하여 leaf→merge 관계를 시각적으로 표현한다.

## File 1: `client/src/types/Valuator.ts`

### 1-1. 트리 노드 타입 추가 (line 178 뒤)

```ts
export interface ValuatorTaskTreeNode {
  task: ValuatorTaskView
  children: ValuatorTaskTreeNode[]
}
```

### 1-2. `ValuatorSubQueryGroup`에 `taskTree` 필드 추가 (line 180-184)

```ts
// before
export interface ValuatorSubQueryGroup {
  unit_id: number
  label: string
  tasks: ValuatorTaskView[]
}

// after
export interface ValuatorSubQueryGroup {
  unit_id: number
  label: string
  tasks: ValuatorTaskView[]
  taskTree: ValuatorTaskTreeNode[]
}
```

---

## File 2: `client/src/composables/useValuatorGraph.ts`

전체 파일을 아래로 교체:

```ts
import { computed, type Ref } from 'vue'
import type {
  ValuatorComputedTaskStatus,
  ValuatorSnapshot,
  ValuatorSubQueryGroup,
  ValuatorTaskTreeNode,
  ValuatorTaskView
} from '../types/Valuator'

export function useValuatorGraph(snapshot: Ref<ValuatorSnapshot | null>) {
  const subQueryGroups = computed<ValuatorSubQueryGroup[]>(() => {
    const current = snapshot.value
    if (!current) {
      return []
    }

    const queryUnits = current.plan.query_units || []
    const tasks = current.plan.tasks || []
    const rootTaskId = current.plan.root_task_id || ''

    const executedTaskIds = new Set(
      (current.execution?.artifacts || []).map((a) => a.task_id)
    )
    const aggregatedTaskIds = new Set(
      (current.aggregation?.reports || []).map((r) => r.task_id)
    )

    const reviewStatus = String(current.review?.status || '').toLowerCase()
    const snapshotStatus = String(current.status || '').toLowerCase()
    const isTerminal =
      reviewStatus === 'pass' || snapshotStatus === 'completed' || snapshotStatus === 'failed'

    return queryUnits.map((unit, unitId) => {
      // root task는 상단에 별도 표시하므로 제외, 그 외 leaf+merge 모두 포함
      const unitTasks = tasks
        .filter(
          (task) =>
            task.id !== rootTaskId &&
            task.query_unit_ids.some((raw) => Number(raw) === unitId)
        )
        .map<ValuatorTaskView>((task) => ({
          ...task,
          computed_status: deriveTaskStatus(
            task.id,
            task.task_type,
            executedTaskIds,
            aggregatedTaskIds,
            isTerminal
          )
        }))

      const label =
        typeof unit === 'string'
          ? unit
          : unit.objective || unit.retrieval_query || unit.id || `Query Unit ${unitId + 1}`

      return {
        unit_id: unitId,
        label,
        tasks: unitTasks,
        taskTree: buildTaskTree(unitTasks)
      }
    })
  })

  const rootTask = computed(() => {
    const current = snapshot.value
    if (!current) {
      return null
    }
    const rootTaskId = current.plan.root_task_id
    if (!rootTaskId) {
      return null
    }
    return current.plan.tasks.find((task) => task.id === rootTaskId) || null
  })

  return {
    subQueryGroups,
    rootTask
  }
}

/**
 * merge 태스크를 top-level, 그 deps 중 이 그룹에 속하는 leaf를 children으로 배치.
 * merge에 속하지 않는 orphan leaf는 top-level에 표시.
 */
function buildTaskTree(tasks: ValuatorTaskView[]): ValuatorTaskTreeNode[] {
  const taskMap = new Map(tasks.map((t) => [t.id, t]))

  // merge 태스크의 children이 되는 task ID 수집
  const childIds = new Set<string>()
  for (const task of tasks) {
    if (task.task_type === 'merge') {
      for (const depId of task.deps) {
        if (taskMap.has(depId)) {
          childIds.add(depId)
        }
      }
    }
  }

  // top-level: merge 태스크 + orphan leaf (어떤 merge의 dep도 아닌 leaf)
  return tasks
    .filter((t) => !childIds.has(t.id))
    .map((t) => ({
      task: t,
      children:
        t.task_type === 'merge'
          ? t.deps
              .filter((depId) => taskMap.has(depId))
              .map((depId) => ({ task: taskMap.get(depId)!, children: [] }))
          : []
    }))
}

function deriveTaskStatus(
  taskId: string,
  taskType: string,
  executedTaskIds: Set<string>,
  aggregatedTaskIds: Set<string>,
  isTerminal: boolean
): ValuatorComputedTaskStatus {
  if (taskType === 'merge') {
    if (aggregatedTaskIds.has(taskId)) {
      return 'ready'
    }
  } else {
    if (executedTaskIds.has(taskId)) {
      return 'ready'
    }
  }

  if (isTerminal) {
    return 'ready'
  }

  return 'pending'
}
```

---

## File 3: `client/src/pages/ValuatorSessionPage.vue`

### 3-1. 상단 live strip aggregation 분모 수정

**line 209-211** — `totalTaskCount` computed 추가:
```ts
// before
const totalLeafTaskCount = computed(
  () => snapshot.value?.plan.tasks.filter((task) => task.task_type === 'leaf').length || 0
)

// after (totalLeafTaskCount 유지 — progress bar에서 사용)
const totalLeafTaskCount = computed(
  () => snapshot.value?.plan.tasks.filter((task) => task.task_type === 'leaf').length || 0
)
const totalTaskCount = computed(
  () => snapshot.value?.plan.tasks.length || 0
)
```

**line 15** — template에서 aggregation 분모 변경:
```html
<!-- before -->
<span class="valuator-live-meta">Aggregation {{ aggregationCount }} / {{ totalLeafTaskCount }}</span>

<!-- after -->
<span class="valuator-live-meta">Aggregation {{ aggregationCount }} / {{ totalTaskCount }}</span>
```

### 3-2. Tasks 패널 트리 렌더링 (line 97-117 교체)

```html
<!-- before -->
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

<!-- after -->
<div v-else class="valuator-task-list">
  <div v-for="node in selectedGroup.taskTree" :key="node.task.id" class="valuator-task-tree-node">
    <article class="valuator-task-card">
      <div class="valuator-task-card-header">
        <router-link
          class="valuator-task-link"
          :to="`/sessions/${sessionId}/tasks/${node.task.id}`"
        >
          {{ node.task.id }}
        </router-link>
        <span
          class="valuator-task-status"
          :class="`valuator-task-status-${node.task.computed_status}`"
        >
          {{ node.task.computed_status }}
        </span>
      </div>
      <p class="valuator-task-desc">{{ node.task.description }}</p>
      <p v-if="showExecution && node.task.tool" class="valuator-task-tool">
        tool: {{ node.task.tool.name }}
      </p>
    </article>
    <div v-if="node.children.length > 0" class="valuator-task-children">
      <article
        v-for="child in node.children"
        :key="child.task.id"
        class="valuator-task-card"
      >
        <div class="valuator-task-card-header">
          <router-link
            class="valuator-task-link"
            :to="`/sessions/${sessionId}/tasks/${child.task.id}`"
          >
            {{ child.task.id }}
          </router-link>
          <span
            class="valuator-task-status"
            :class="`valuator-task-status-${child.task.computed_status}`"
          >
            {{ child.task.computed_status }}
          </span>
        </div>
        <p class="valuator-task-desc">{{ child.task.description }}</p>
        <p v-if="showExecution && child.task.tool" class="valuator-task-tool">
          tool: {{ child.task.tool.name }}
        </p>
      </article>
    </div>
  </div>
</div>
```

### 3-3. CSS 추가 (`.valuator-task-card` 스타일 뒤, line 1023 부근)

```css
.valuator-task-tree-node {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.valuator-task-children {
  padding-left: 1.5rem;
  border-left: 2px solid var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
```

### 3-4. import 수정 (line 158)

```ts
// before
import type { ValuatorSnapshot, ValuatorSubQueryGroup } from '../types/Valuator'

// after (ValuatorSubQueryGroup은 여전히 사용 — subQueryStatus, readyTaskCount 등)
import type { ValuatorSnapshot, ValuatorSubQueryGroup } from '../types/Valuator'
```
→ import 변경 없음. `ValuatorTaskTreeNode`은 template에서만 사용하므로 import 불필요.

---

## Verification

1. `cd client && npm run dev`
2. 기존 세션 페이지 열기
3. Q1 선택 시:
   - T-MERGE-1 카드 아래 들여쓰기로 T-LEAF-1, T-LEAF-6 표시
   - 3개 태스크 모두 status badge 정상
4. Aggregation: `Reports 3 / 3` 확인 (leaf 2 + merge 1)
5. 상단 live strip: `Aggregation X / totalTaskCount` (전체 태스크 수 기준)
6. Sub-query Markdown: merge 태스크의 aggregation markdown 포함
7. 각 sub-query (Q1~Q5) 전환 시 트리 구조 정상 렌더링
