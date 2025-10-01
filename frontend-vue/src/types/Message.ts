export interface Message {
  type: 'thought' | 'action' | 'observation' | 'final_answer' | 'error' | 'token'
  content: string
  metadata?: any
  timestamp: Date
}

export type MessageType = Message['type']

export interface MessageMetadata {
  tool?: string
  error?: string
  message?: string
}
