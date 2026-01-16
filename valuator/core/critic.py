from abc import ABC, abstractmethod


class Critic(ABC):
    @abstractmethod
    async def review_task_outputs(self, task_id: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def review(
        self,
        task_id: str,
        verdict: str,
        findings: list[dict] | None = None,
        required_fixes: list[str] | None = None,
        knowledge_paths: list[str] | None = None,
    ) -> dict:
        raise NotImplementedError
