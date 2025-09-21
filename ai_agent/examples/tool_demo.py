"""Tool demo for AI Agent"""

import asyncio
from typing import List, Dict, Any

from ..agent.core import GeminiAgent
from ..tools.base import ToolRegistry
from ..utils.config import config
from ..utils.logger import logger


class ToolDemo:
    """Demo for AI Agent with tools"""
    
    def __init__(self):
        """Initialize tool demo"""
        self.agent = None
        self.tool_registry = ToolRegistry()
    
    async def initialize(self):
        """Initialize the agent with tools"""
        try:
            self.agent = GeminiAgent()
            
            # Register tools
            # Tools can be registered here
            
            # Custom system prompt for tool demo
            demo_prompt = """You are a helpful AI assistant with access to various tools.
You can search the web and perform various tasks.

Available tools:
- web_search: Search the web (requires API key)

When a user asks you to use a tool, you should use the appropriate tool and provide the results."""
            
            # Set custom prompt
            self.agent.set_system_prompt(demo_prompt)
            
            logger.info("Tool demo initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize tool demo: {e}")
            return False
    
    async def run_basic_demo(self):
        """Run basic tool demo"""
        if not self.agent:
            print("Agent not initialized. Please run initialize() first.")
            return
        
        print("=" * 60)
        print("🔧 Basic Tool Demo")
        print("=" * 60)
        print("You can chat with the AI agent here.")
        print("Type 'quit' to exit")
        print("=" * 60)
        
        while True:
            try:
                user_input = input("\n👤 You: ").strip()
                
                if user_input.lower() in ['quit', 'exit', 'bye']:
                    break
                
                if not user_input:
                    continue
                
                # Regular chat response
                print("🤖 Agent: ", end="", flush=True)
                async for chunk in self.agent.chat_stream(user_input):
                    print(chunk, end="", flush=True)
                print()
                    
            except KeyboardInterrupt:
                print("\n\n👋 Demo interrupted. Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                logger.error(f"Tool demo error: {e}")
    
    async def show_available_tools(self):
        """Show available tools"""
        tools = self.tool_registry.list_tools()
        
        print("\n🔧 Available Tools:")
        if tools:
            for tool in tools:
                print(f"  • {tool['name']}: {tool['description']}")
        else:
            print("  No tools currently registered.")


async def main():
    """Main function to run tool demo"""
    demo = ToolDemo()
    
    # Initialize agent
    if await demo.initialize():
        print("Welcome to AI Agent Tool Demo!")
        await demo.show_available_tools()
        await demo.run_basic_demo()
    else:
        print("❌ Failed to initialize agent. Please check your configuration.")


if __name__ == "__main__":
    asyncio.run(main())