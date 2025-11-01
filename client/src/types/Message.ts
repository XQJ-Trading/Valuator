export interface Message {
  type: 'planning' | 'thought' | 'action' | 'observation' | 'final_answer' | 'error' | 'token' | 'start' | 'end' | 'subtask_result'
  content: string
  metadata?: MessageMetadata
  timestamp: Date
}

export type MessageType = Message['type']

export interface MessageMetadata {
  tool?: string
  tool_input?: any
  tool_output?: any
  error?: string
  message?: string
  tool_result?: ToolResult
  query?: string
  source_type?: string
  original_content?: string
  todo?: string  // Planning step의 todo markdown
}

export interface ToolResult {
  success: boolean
  result: any
  error?: string
  metadata?: Record<string, any>
}
