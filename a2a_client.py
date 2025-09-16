import asyncio
from uuid import uuid4

from devtools import pprint

import httpx

from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.types import (
    Message,
    TextPart,
)


# ANSI color codes
class Colors:
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    DIM = '\033[2m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


class A2AREPL:
    def __init__(self, base_url: str = 'http://localhost:9999'):
        self.base_url = base_url
        self.client = None
        self.httpx_client = None
        self.agent_name = None
        self.context_id = None

    async def initialize(self):
        """Initialize the client by fetching agent card and setting up connection"""
        self.httpx_client = httpx.AsyncClient()

        resolver = A2ACardResolver(
            httpx_client=self.httpx_client,
            base_url=self.base_url,
        )

        try:
            print(f"{Colors.DIM}Connecting to {self.base_url}...{Colors.RESET}")
            agent_card = await resolver.get_agent_card()
            self.agent_name = agent_card.name

            config = ClientConfig(httpx_client=self.httpx_client)
            factory = ClientFactory(config)
            self.client = factory.create(agent_card)

        except Exception as e:
            print(f"{Colors.RED}Connection failed: {e}{Colors.RESET}")
            raise

    async def send_message(self, text: str, use_streaming: bool = False, debug: bool = False):
        """Send a message to the agent"""
        if not self.client:
            raise RuntimeError("Client not initialized. Call initialize() first.")

        # Create message with new API
        message = Message(
            message_id=uuid4().hex,
            role='user', # type: ignore
            parts=[TextPart(text=text)], # type: ignore
            context_id=self.context_id,
        )

        try:
            # The new send_message method returns an async iterator
            async for event in self.client.send_message(message):
                # Debug: Print the entire event structure (if debug mode is enabled)
                if debug:
                    print()
                    print(f"{Colors.YELLOW}DEBUG - Full event{Colors.RESET}")
                    pprint(event.__dict__)
                    print()

                # Handle different event types
                if isinstance(event, Message):
                    # Store context_id from server response
                    if event.context_id and not self.context_id:
                        self.context_id = event.context_id
                        if debug:
                            print(f"{Colors.GREEN}Stored context_id: {self.context_id}{Colors.RESET}")

                    # Final message response
                    for part in event.parts:
                        if hasattr(part, 'root') and hasattr(part.root, 'text'):
                            if use_streaming:
                                print()  # Add newline after streaming
                            print(part.root.text)
                elif isinstance(event, tuple):
                    # Task and event updates (task, event)
                    task, update_event = event
                    if update_event and hasattr(update_event, 'artifacts'):
                        # Handle artifact updates for streaming
                        for artifact in update_event.artifacts:
                            if hasattr(artifact, 'data') and hasattr(artifact.data, 'text'):
                                if use_streaming:
                                    print(artifact.data.text, end='', flush=True)
                                else:
                                    print(artifact.data.text)

        except Exception as e:
            print(f"{Colors.RED}Error: {e}{Colors.RESET}")

    def show_welcome(self):
        """Display welcome banner and commands"""
        agent_display = f" {self.agent_name}" if self.agent_name else ""
        print(f"\n{Colors.BOLD}a2a{agent_display}{Colors.RESET}")
        print(f"{Colors.DIM}> You are connected to an A2A agent{Colors.RESET}")
        print()
        print(f"{Colors.DIM}To get started, type a message or try one of these commands:{Colors.RESET}")
        print()
        print(f"{Colors.CYAN}/stream{Colors.RESET} {Colors.DIM}- toggle streaming mode{Colors.RESET}")
        print(f"{Colors.CYAN}/debug{Colors.RESET}  {Colors.DIM}- toggle debug mode{Colors.RESET}")
        print(f"{Colors.CYAN}/clear{Colors.RESET}  {Colors.DIM}- clear conversation context{Colors.RESET}")
        print(f"{Colors.CYAN}/help{Colors.RESET}   {Colors.DIM}- show this help{Colors.RESET}")
        print(f"{Colors.CYAN}/quit{Colors.RESET}   {Colors.DIM}- exit the session{Colors.RESET}")
        print()

    async def run_repl(self):
        """Run the interactive REPL"""
        await self.initialize()
        self.show_welcome()

        use_streaming = False
        debug_mode = False

        while True:
            try:
                prompt = f"{Colors.CYAN}{'[streaming] ' if use_streaming else ''}{'[debug] ' if debug_mode else ''}> {Colors.RESET}"
                user_input = input(prompt).strip()

                if not user_input:
                    continue

                if user_input in ['/quit', '/exit']:
                    print(f"{Colors.DIM}Goodbye!{Colors.RESET}")
                    break
                elif user_input == '/stream':
                    use_streaming = not use_streaming
                    status = f"{Colors.GREEN}ON{Colors.RESET}" if use_streaming else f"{Colors.DIM}OFF{Colors.RESET}"
                    print(f"{Colors.DIM}Streaming mode: {status}{Colors.RESET}")
                    continue
                elif user_input == '/debug':
                    debug_mode = not debug_mode
                    status = f"{Colors.GREEN}ON{Colors.RESET}" if debug_mode else f"{Colors.DIM}OFF{Colors.RESET}"
                    print(f"{Colors.DIM}Debug mode: {status}{Colors.RESET}")
                    continue
                elif user_input == '/clear':
                    self.context_id = None
                    print(f"{Colors.DIM}Conversation context cleared{Colors.RESET}")
                    continue
                elif user_input == '/help':
                    print(f"{Colors.CYAN}/stream{Colors.RESET} {Colors.DIM}- toggle streaming mode{Colors.RESET}")
                    print(f"{Colors.CYAN}/debug{Colors.RESET}  {Colors.DIM}- toggle debug mode{Colors.RESET}")
                    print(f"{Colors.CYAN}/clear{Colors.RESET}  {Colors.DIM}- clear conversation context{Colors.RESET}")
                    print(f"{Colors.CYAN}/help{Colors.RESET}   {Colors.DIM}- show this help{Colors.RESET}")
                    print(f"{Colors.CYAN}/quit{Colors.RESET}   {Colors.DIM}- exit the session{Colors.RESET}")
                    continue

                await self.send_message(user_input, use_streaming, debug_mode)
                print()

            except KeyboardInterrupt:
                print(f"\n{Colors.DIM}Goodbye!{Colors.RESET}")
                break
            except Exception as e:
                print(f"{Colors.RED}Error: {e}{Colors.RESET}")

    async def cleanup(self):
        """Clean up resources"""
        if self.httpx_client:
            await self.httpx_client.aclose()


async def main() -> None:
    repl = A2AREPL()

    try:
        await repl.run_repl()
    finally:
        await repl.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
