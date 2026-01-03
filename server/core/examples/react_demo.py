"""AI Agent demonstration examples"""

import asyncio
import json
import os
from typing import Any, Dict, Optional

from ..agent.react_agent import AIAgent
from ..utils.logger import logger
from ..utils.react_logger import list_all_sessions, view_session_log


class AIAgentDemo:
    """Demonstration of AI Agent capabilities"""

    def __init__(self):
        """Initialize AI Agent demo"""
        self.agent = AIAgent()
        self.default_context: Dict[str, Any] = self._load_context_from_env()

    def _load_context_from_env(self) -> Dict[str, Any]:
        """Load default context from REACT_DEMO_CONTEXT env (JSON object)."""
        raw = os.getenv("REACT_DEMO_CONTEXT")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            print("⚠️  REACT_DEMO_CONTEXT must be a JSON object; ignoring.")
            return {}
        except Exception as e:
            print(f"⚠️  Failed to parse REACT_DEMO_CONTEXT: {e}")
            return {}

    async def initialize(self) -> bool:
        """Initialize the demo (agent is already ready)"""
        try:
            print("🔧 Initializing AI Agent Demo...")

            # Agent is automatically initialized with ReAct capabilities
            if self.agent.is_ready():
                print("✅ AI Agent initialized")
                print(f"✅ {len(self.agent.get_available_tools())} tools available")
                if self.default_context:
                    print("🧩 Context loaded from REACT_DEMO_CONTEXT")
                return True
            else:
                print("❌ Agent not ready")
                return False

        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            logger.error(f"AI Agent demo initialization error: {e}")
            return False

    async def run_interactive_demo(self):
        """Run interactive ReAct demo"""
        print("\n🚀 Welcome to ReAct Interactive Demo!")
        print("=" * 60)
        print("ReAct (Reasoning + Acting) will solve problems step by step:")
        print("• Thought: Analyzes the situation and plans next action")
        print("• Action: Executes tools or performs tasks")
        print("• Observation: Reviews results and decides next steps")
        print("• Repeats until problem is solved")
        print(
            "\nType 'quit' to exit, 'examples' for sample problems, 'logs' to view session logs"
        )
        print("=" * 60)

        while True:
            try:
                print("\n💭 What problem would you like ReAct to solve?")
                user_input = input("Query: ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ["quit", "exit", "q"]:
                    print("👋 Goodbye!")
                    break

                if user_input.lower() == "examples":
                    self._show_example_problems()
                    continue

                if user_input.lower() == "logs":
                    self._show_session_logs()
                    continue

                # Run ReAct solving
                await self._solve_with_react(user_input, context=self.default_context)

            except KeyboardInterrupt:
                print("\n\n👋 Demo interrupted. Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                logger.error(f"Interactive demo error: {e}")

    async def run_predefined_examples(self):
        """Run predefined ReAct examples"""
        print("\n🚀 Running Predefined ReAct Examples...")
        print("=" * 60)

        examples = [
            {
                "name": "Mathematical Problem Solving",
                "query": "Calculate the compound interest on $1000 at 5% annual interest for 3 years, then explain what this means",
                "description": "Tests mathematical reasoning and explanation capabilities",
            },
            {
                "name": "Advanced Research with Query Expansion",
                "query": "What are the latest developments in quantum computing and their potential impact on various industries?",
                "description": "Tests comprehensive information gathering using query expansion",
            },
            {
                "name": "Code Generation and Execution",
                "query": "Write a Python function to find prime numbers up to 100 and test it",
                "description": "Tests code creation and validation",
            },
            {
                "name": "File Operations",
                "query": "Create a simple todo list in a text file and then read it back to verify",
                "description": "Tests file system operations",
            },
        ]

        for i, example in enumerate(examples, 1):
            print(f"\n📋 Example {i}: {example['name']}")
            print(f"Description: {example['description']}")
            print(f"Query: {example['query']}")
            print("-" * 60)

            try:
                await self._solve_with_react(
                    example["query"],
                    show_progress=True,
                    context=self.default_context,
                )

                # Wait for user to continue
                input("\nPress Enter to continue to next example...")

            except Exception as e:
                print(f"❌ Example {i} failed: {e}")
                logger.error(f"Example {i} error: {e}")

        print("\n✅ All examples completed!")

    async def _solve_with_react(
        self,
        query: str,
        show_progress: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Solve a problem using ReAct and display results"""
        if show_progress:
            print("\n🔍 Starting ReAct solving process...")
            print(f"Query: {query}")

        print("\n" + "=" * 80)
        print("🧠 REACT REASONING PROCESS")
        print("=" * 80)

        # Solve using AI Agent
        start_time = asyncio.get_event_loop().time()

        # Collect events from solve_stream
        events = []
        async for event in self.agent.solve_stream(query, context or {}):
            events.append(event)

        # Extract final state from events
        final_event = events[-1] if events else None
        state = final_event.get("react_state") if final_event else None

        end_time = asyncio.get_event_loop().time()

        # Display the reasoning process
        self._display_react_process(state)

        # Display final results
        print("\n" + "=" * 80)
        print("📊 RESULTS")
        print("=" * 80)

        if state.is_completed and not state.error:
            print("✅ Problem solved successfully!")
            print(f"\n🎯 Final Answer:\n{state.final_answer}")
        else:
            print("❌ Problem solving incomplete")
            if state.error:
                print(f"Error: {state.error}")

        print(f"\n⏱️  Total time: {end_time - start_time:.2f} seconds")
        print(f"🔄 Steps taken: {state.current_step}")
        print(
            f"🛠️  Tools used: {len(set(s.tool_name for s in state.steps if s.tool_name))}"
        )

        return state

    def _display_react_process(self, state):
        """Display the ReAct reasoning process"""
        step_count = {"thought": 0, "action": 0, "observation": 0}

        for step in state.steps:
            if step.step_type.value == "thought":
                step_count["thought"] += 1
                print(f"\n💭 Thought {step_count['thought']}:")
                print(f"   {step.content}")

            elif step.step_type.value == "action":
                step_count["action"] += 1
                print(f"\n⚡ Action {step_count['action']}:")
                print(f"   {step.content}")
                if step.tool_name:
                    print(f"   🛠️  Tool: {step.tool_name}")
                    if step.tool_input:
                        print(f"   📥 Input: {step.tool_input}")

            elif step.step_type.value == "observation":
                step_count["observation"] += 1
                print(f"\n👁️  Observation {step_count['observation']}:")
                print(f"   {step.content}")
                if step.error:
                    print(f"   ❌ Error: {step.error}")
                elif step.tool_output:
                    print(f"   📤 Output: {step.tool_output}")

    def _show_example_problems(self):
        """Show example problems that work well with ReAct"""
        examples = [
            "Calculate the area of a circle with radius 5 and explain the formula",
            "Research the capital city of Japan and provide 3 interesting facts",
            "Write Python code to sort a list [3,1,4,1,5] and execute it",
            "Create a simple shopping list file and then read it back",
            "Analyze the pros and cons of electric vehicles",
            "Find the square root of 144 using different methods",
            "Generate a random password and explain how to make it secure",
        ]

        print("\n📝 Example Problems for ReAct:")
        print("-" * 40)
        for i, example in enumerate(examples, 1):
            print(f"{i}. {example}")
        print("\nJust copy and paste any of these, or create your own!")

    def _show_session_logs(self):
        """Show ReAct session logs"""
        print("\n📋 ReAct Session Logs")
        print("-" * 40)
        print("1. View recent sessions")
        print("2. List all sessions")
        print("3. View specific session")

        choice = input("\nChoose option (1-3): ").strip()

        if choice == "1":
            view_session_log()
        elif choice == "2":
            list_all_sessions()
        elif choice == "3":
            session_file = input("Enter session filename: ").strip()
            if session_file:
                view_session_log(session_file)
        else:
            print("Invalid choice")

    async def demonstrate_specific_capability(self, capability: str):
        """Demonstrate a specific ReAct capability"""
        demos = {
            "reasoning": "Explain why the sky is blue using scientific principles",
            "calculation": "Calculate the monthly payment for a $200,000 mortgage at 4% for 30 years",
            "research": "Research the history of artificial intelligence and provide a timeline",
            "coding": "Write a function to check if a number is prime and test it with several examples",
            "analysis": "Compare the advantages and disadvantages of solar vs wind energy",
        }

        if capability in demos:
            query = demos[capability]
            print(f"\n🎯 Demonstrating {capability.title()} Capability")
            print(f"Query: {query}")
            await self._solve_with_react(query, context=self.default_context)
        else:
            print(f"❌ Unknown capability: {capability}")
            print(f"Available: {', '.join(demos.keys())}")


async def main():
    """Main demo function"""
    demo = AIAgentDemo()

    if not await demo.initialize():
        return

    print("\nChoose demo mode:")
    print("1. Interactive ReAct Demo")
    print("2. Predefined Examples")
    print("3. Specific Capability Demo")

    while True:
        choice = input("\nEnter choice (1-3) or 'quit': ").strip()

        if choice.lower() in ["quit", "exit", "q"]:
            print("👋 Goodbye!")
            break
        elif choice == "1":
            await demo.run_interactive_demo()
            break
        elif choice == "2":
            await demo.run_predefined_examples()
            break
        elif choice == "3":
            capability = input(
                "Enter capability (reasoning/calculation/research/coding/analysis): "
            ).strip()
            await demo.demonstrate_specific_capability(capability)
            break
        else:
            print("❌ Invalid choice. Please enter 1, 2, 3, or 'quit'.")


if __name__ == "__main__":
    asyncio.run(main())
