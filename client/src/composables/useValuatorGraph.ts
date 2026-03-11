import { computed, type Ref } from 'vue'
import type {
  ValuatorComputedTaskStatus,
  ValuatorSnapshot,
  ValuatorSubQueryGroup,
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
    const completedTaskIds = new Set(
      (current.execution?.artifacts || []).map((artifact) => artifact.task_id)
    )
    const reviewStatus = String(current.review?.status || '').toLowerCase()
    const snapshotStatus = String(current.status || '').toLowerCase()
    const isTerminal =
      reviewStatus === 'pass' || snapshotStatus === 'completed' || snapshotStatus === 'failed'

    return queryUnits.map((unit, unitId) => {
      const unitTasks = tasks
        .filter(
          (task) => task.task_type === 'leaf' && task.query_unit_ids.some((raw) => Number(raw) === unitId)
        )
        .map<ValuatorTaskView>((task) => ({
          ...task,
          computed_status: deriveTaskStatus(task.id, completedTaskIds, isTerminal)
        }))
      const label =
        typeof unit === 'string'
          ? unit
          : unit.objective || unit.retrieval_query || unit.id || `Query Unit ${unitId + 1}`

      return {
        unit_id: unitId,
        label,
        tasks: unitTasks
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

function deriveTaskStatus(
  taskId: string,
  completedTaskIds: Set<string>,
  isTerminal: boolean
): ValuatorComputedTaskStatus {
  if (completedTaskIds.has(taskId)) {
    return 'ready'
  }

  if (isTerminal) {
    return 'ready'
  }

  return 'pending'
}
