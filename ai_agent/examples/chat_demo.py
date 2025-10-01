"""Chat demo for AI Agent"""

import asyncio
from typing import Optional

from ..agent.react_agent import AIAgent
from ..utils.config import config
from ..utils.logger import logger


class ChatDemo:
    """Interactive chat demo for AI Agent"""
    
    def __init__(self):
        """Initialize chat demo"""
        self.agent = None
    
    async def initialize(self):
        """Initialize the agent"""
        try:
            self.agent = AIAgent()
            
            # Custom system prompt for demo
            demo_prompt = """You are a helpful AI assistant in a demo environment. 
You can engage in conversations, answer questions, and help with various tasks.
This is a demonstration of the Gemini Agent capabilities.

Please be friendly and helpful while showcasing your abilities."""
            
            self.agent.set_system_prompt(demo_prompt)
            
            logger.info("Chat demo initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize chat demo: {e}")
            return False
    
    async def run_interactive_chat(self):
        """Run interactive chat session"""
        if not self.agent:
            print("Agent not initialized. Please run initialize() first.")
            return
        
        print("=" * 60)
        print("🤖 Gemini AI Agent Chat Demo")
        print("=" * 60)
        print("Type 'quit', 'exit', or 'bye' to end the conversation")
        print("Type 'status' to see agent status")
        print("Type 'help' to see available commands")
        print("=" * 60)
        
        while True:
            try:
                # Get user input
                user_input = input("\n👤 You: ").strip()
                
                if not user_input:
                    continue
                
                # Handle special commands
                if user_input.lower() in ['quit', 'exit', 'bye']:
                    print("👋 Goodbye! Thanks for using Gemini Agent!")
                    break
                
                
                elif user_input.lower() == 'status':
                    await self._show_status()
                    continue
                
                elif user_input.lower() == 'help':
                    await self._show_help()
                    continue
                
                # Process user message
                print("🤖 Agent: ", end="", flush=True)
                
                # Generate and stream response
                response_content = ""
                async for chunk in self.agent.chat_stream(user_input):
                    print(chunk, end="", flush=True)
                    response_content += chunk
                
                print()  # New line after response
                
            except KeyboardInterrupt:
                print("\n\n👋 Chat interrupted. Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                logger.error(f"Chat error: {e}")
    
    async def run_single_query(self, query: str) -> str:
        """Run a single query and return response"""
        if not self.agent:
            await self.initialize()
        
        if not self.agent:
            return "Failed to initialize agent"
        
        try:
            response = await self.agent.chat(query)
            return response
        except Exception as e:
            logger.error(f"Single query error: {e}")
            return f"Error: {e}"
    
    async def _show_status(self):
        """Show agent status"""
        if not self.agent:
            print("\n❌ Agent not initialized")
            return
            
        status = self.agent.get_status()
        
        print("\n📊 Agent Status:")
        print(f"  • Model: {status['model_info']['model_name']}")
        print(f"  • Version: {status['model_info']['agent_version']}")
        print(f"  • Ready: {'✅' if status['ready'] else '❌'}")
    
    async def _show_help(self):
        """Show help information"""
        print("\n📖 Available Commands:")
        print("  • Type your message normally to chat with the agent")
        print("  • 'status' - Show agent status")
        print("  • 'help' - Show this help message")
        print("  • 'quit', 'exit', 'bye' - End the conversation")
        print("\n💡 Tips:")
        print("  • Ask questions about any topic")
        print("  • Request help with tasks or problems")
        print("  • Try asking for explanations or summaries")


async def main():
    """Main function to run chat demo"""
    demo = ChatDemo()
    
    # Initialize agent
    if await demo.initialize():
        # Run interactive chat
        await demo.run_interactive_chat()
    else:
        print("❌ Failed to initialize agent. Please check your configuration.")


if __name__ == "__main__":
    asyncio.run(main())
