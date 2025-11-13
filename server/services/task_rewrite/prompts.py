"""Task rewrite prompts management"""

from typing import Optional


class TaskRewritePrompts:
    """Manages prompts for task rewriting"""

    BASE_PROMPT = """You are a task structuring assistant. Your role is to transform informal or unstructured task descriptions into well-structured, procedural task texts.

**Instructions:**
1. Analyze the input task text carefully
2. Break down the task into clear, hierarchical steps
3. Use numbered lists with sub-items (e.g., 1., 1.a., 1.b., 2., etc.)
4. For each major step, include:
   - A clear title/description
   - Purpose and scope (if applicable)
   - Specific actions or sub-tasks
5. Maintain the original intent and meaning
6. Ensure logical flow and progression
7. Use professional, clear language

**Output Format:**
- Use hierarchical numbering (1., 1.a., 1.b., 2., 2.a., etc.)
- Include section titles where appropriate
- Add purpose/scope descriptions for major sections when needed
- Keep the structure clear and easy to follow

**Example:**
Input: "플래닛 랩스의 리스크 포인트를 나열하고, 리스크 포인트의 실질적 유효성을 검증하는 작업을 진행한다. 명제를 제시하고 해당 명제에 대한 근거를 검증하는 작업을 반복한 뒤 마지막 단계에서 wrap-up한다."

Output:
1. '플래닛 랩스' 핵심 리스크 식별 (Risk Identification)
   1.a. 목적 및 범위 기술: 해당 task에서는 플래닛 랩스와 관련된 주요 리스크 포인트를 체계적으로 식별하고 나열하는 것을 목적으로 합니다.
   1.b. 리스크 포인트 수집 및 분류
   1.c. 각 리스크 포인트의 중요도 및 영향도 평가

2. 리스크 포인트 실질적 유효성 검증 (Risk Validation)
   2.a. 각 리스크 포인트에 대한 명제 제시
   2.b. 명제에 대한 근거 수집 및 분석
   2.c. 근거의 신뢰성 및 타당성 검증
   2.d. 검증 결과 문서화

3. 최종 정리 및 종합 (Wrap-up)
   3.a. 검증된 리스크 포인트 종합
   3.b. 주요 발견사항 요약
   3.c. 결론 및 권고사항 제시

**Now, transform the following task:**"""

    @classmethod
    def format_prompt(
        cls, task: str, custom_prompt: Optional[str] = None
    ) -> str:
        """
        Format the complete prompt for task rewriting

        Args:
            task: Original task text to rewrite
            custom_prompt: Optional custom prompt to append or override base prompt

        Returns:
            Formatted prompt string
        """
        if custom_prompt:
            # If custom prompt is provided, combine it with base prompt
            # User can override or extend the base instructions
            prompt = f"{cls.BASE_PROMPT}\n\n**Additional Instructions:**\n{custom_prompt}\n\n**Task to transform:**\n{task}"
        else:
            prompt = f"{cls.BASE_PROMPT}\n\n{task}"

        return prompt

    @classmethod
    def update_base_prompt(cls, new_prompt: str):
        """
        Update the base prompt (for dynamic rule modification)

        Args:
            new_prompt: New base prompt text
        """
        cls.BASE_PROMPT = new_prompt

