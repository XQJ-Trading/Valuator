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
      (current.execution?.artifacts || []).map((artifact) => artifact.task_id)
    )
    const aggregatedTaskIds = new Set(
      (current.aggregation?.reports || []).map((report) => report.task_id)
    )
    const reviewStatus = String(current.review?.status || '').toLowerCase()
    const snapshotStatus = String(current.status || '').toLowerCase()
    const isTerminal =
      reviewStatus === 'pass' || snapshotStatus === 'completed' || snapshotStatus === 'failed'

    return queryUnits.map((unit, unitId) => {
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

function buildTaskTree(tasks: ValuatorTaskView[]): ValuatorTaskTreeNode[] {
  const taskMap = new Map(tasks.map((task) => [task.id, task]))
  const childIds = new Set<string>()

  for (const task of tasks) {
    if (task.task_type !== 'merge') {
      continue
    }
    for (const depId of task.deps) {
      if (taskMap.has(depId)) {
        childIds.add(depId)
      }
    }
  }

  return tasks
    .filter((task) => !childIds.has(task.id))
    .map((task) => ({
      task,
      children:
        task.task_type === 'merge'
          ? task.deps
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
  } else if (executedTaskIds.has(taskId)) {
    return 'ready'
  }

  if (isTerminal) {
    return 'ready'
  }

  return 'pending'
}
