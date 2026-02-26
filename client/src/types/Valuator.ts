export type ValuatorSessionStatus = 'running' | 'completed' | 'failed' | string

export interface ValuatorSessionSummary {
  session_id: string
  query: string
  status: ValuatorSessionStatus
  created_at?: string
  completed_at?: string
  event_count?: number
  timestamp?: string
  success?: boolean
}

export interface ValuatorContractItem {
  id: string
  unit_id: number
  requirement_type: string
  acceptance: string
  required: boolean
}

export interface ValuatorPlanContract {
  items: ValuatorContractItem[]
  rationale?: string
}

export interface ValuatorToolCall {
  name: string
  args: Record<string, unknown>
}

export interface ValuatorPlanTask {
  id: string
  task_type: 'leaf' | 'merge'
  query_unit_ids: number[]
  deps: string[]
  tool: ValuatorToolCall | null
  output: string
  description: string
  merge_instruction: string
}

export interface ValuatorPlan {
  query_units: string[]
  contract?: ValuatorPlanContract | null
  tasks: ValuatorPlanTask[]
  root_task_id?: string | null
}

export interface ValuatorExecutionArtifact {
  task_id: string
  logical_output_path: string
  tool?: string
  args_hash?: string
  exists?: boolean
}

export interface ValuatorAggregationReport {
  task_id: string
  logical_report_path: string
  exists?: boolean
}

export interface ValuatorReviewAction {
  node: number
  reason: string
}

export interface ValuatorReviewCoverageFeedback {
  summary?: string
  self_assessment?: Record<string, unknown>
  signals?: Record<string, unknown>
}

export interface ValuatorReview {
  status: 'pass' | 'fail' | 'running' | string
  round?: number
  actions: ValuatorReviewAction[]
  coverage_feedback?: ValuatorReviewCoverageFeedback
}

export interface ValuatorSnapshot {
  session_id: string
  query: string
  round?: number
  status?: string
  plan: ValuatorPlan
  execution: {
    artifacts: ValuatorExecutionArtifact[]
  }
  aggregation: {
    reports: ValuatorAggregationReport[]
  }
  review: ValuatorReview
}

export interface ValuatorTaskDetail {
  session_id: string
  task_id: string
  execution_markdown: string
  aggregation_markdown: string
  output_metadata?: Record<string, string>
}

export interface ValuatorFinalDocument {
  session_id: string
  markdown: string
}

export type ValuatorComputedTaskStatus = 'ready' | 'pending' | 'needs-review'

export interface ValuatorTaskView extends ValuatorPlanTask {
  computed_status: ValuatorComputedTaskStatus
}

export interface ValuatorSubQueryGroup {
  unit_id: number
  label: string
  tasks: ValuatorTaskView[]
  has_actions: boolean
}
