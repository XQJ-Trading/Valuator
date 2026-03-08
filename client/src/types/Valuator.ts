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
  unit_ids: number[]
  domain_ids: string[]
  entity_ids: string[]
  provenance: string
  acceptance: string
  required: boolean
  requirement_type?: string
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
  task_type: 'leaf' | 'module' | 'merge'
  query_unit_ids: number[]
  deps: string[]
  tool: ValuatorToolCall | null
  domain_id?: string
  output: string
  description: string
  merge_instruction: string
}

export interface ValuatorQueryUnit {
  id: string
  objective: string
  retrieval_query: string
  domain_ids: string[]
  entity_ids: string[]
  time_scope: string
}

export interface ValuatorPlan {
  query_units: ValuatorQueryUnit[]
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
  signals?: ValuatorReviewSignals
}

export interface ValuatorQueryCoverageSignal {
  total: number
  covered: number
  missing_ids: string[]
  missing_unit_ids: number[]
  ratio: number
}

export interface ValuatorUnitCoverageSignal {
  total: number
  planned: number
  executed: number
  aggregated: number
  final: number
  planned_ids: number[]
  executed_ids: number[]
  aggregated_ids: number[]
  final_ids: number[]
}

export interface ValuatorDomainCoverageSignal {
  selected_total: number
  planned: number
  executed: number
  final: number
  selected_ids: string[]
  planned_ids: string[]
  executed_ids: string[]
  final_ids: string[]
  missing_in_plan: boolean
  missing_in_final: boolean
  missing_in_evidence: boolean
  missing_ids_in_plan: string[]
  missing_ids_in_final: string[]
  missing_ids_in_evidence: string[]
}

export interface ValuatorReviewSignals {
  query?: ValuatorQueryCoverageSignal
  units?: ValuatorUnitCoverageSignal
  domains?: ValuatorDomainCoverageSignal
  missing_leaf?: number
  missing_mapping?: number
  missing_contract?: number
  final_empty?: boolean
  aggregation_error?: number
}

export interface ValuatorReview {
  status: 'pass' | 'revise' | 'fail' | 'running' | string
  round?: number
  actions: ValuatorReviewAction[]
  coverage_feedback?: ValuatorReviewCoverageFeedback
  now_utc?: string
  quant_axes?: Record<string, unknown>
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

export type ValuatorComputedTaskStatus = 'ready' | 'pending'

export interface ValuatorTaskView extends ValuatorPlanTask {
  computed_status: ValuatorComputedTaskStatus
}

export interface ValuatorSubQueryGroup {
  unit_id: number
  label: string
  tasks: ValuatorTaskView[]
}
