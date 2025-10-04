export interface Message {
  type: 'thought' | 'action' | 'observation' | 'final_answer' | 'error' | 'token'
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
}

export interface ToolResult {
  success: boolean
  result: any
  error?: string
  metadata?: Record<string, any>
}
