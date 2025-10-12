import type { MessageType } from '../types/Message'

export function getMessageIcon(type: MessageType): string {
  const icons = {
    thought: '🧠',
    action: '⚡',
    observation: '👁️',
    final_answer: '🎯',
    error: '❌',
    token: '💬',
    start: '🚀',
    end: '✅',
    subtask_result: '📋'
  }
  return icons[type] || '💬'
}

export function getMessageTitle(type: MessageType): string {
  const titles = {
    thought: '사고과정',
    action: '도구 실행',
    observation: '실행 결과',
    final_answer: '최종 답변',
    error: '오류',
    token: '응답',
    start: '처리 시작',
    end: '처리 완료',
    subtask_result: '서브태스크 결과'
  }
  return titles[type] || '메시지'
}

export function formatTime(timestamp: Date): string {
  return timestamp.toLocaleTimeString('ko-KR', { 
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit'
  })
}

export async function copyMessage(content: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(content)
    // TODO: 토스트 알림 추가
  } catch (err) {
    console.error('클립보드 복사 실패:', err)
  }
}
