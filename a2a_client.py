import os
import asyncio
import argparse
import base64
import mimetypes
from pathlib import Path
from uuid import uuid4
from devtools import pprint
import httpx
import re
import traceback

from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.types import (
    Message,
    TextPart,
    FilePart,
    FileWithBytes,
)

from dotenv import load_dotenv

load_dotenv()

# Global configuration
REQUEST_TIMEOUT = 60.0  # seconds


# ANSI color codes
class Colors:
    CYAN: str = "\033[96m"
    BLUE: str = "\033[94m"
    GREEN: str = "\033[92m"
    YELLOW: str = "\033[93m"
    RED: str = "\033[91m"
    DIM: str = "\033[2m"
    BOLD: str = "\033[1m"
    ITALIC: str = "\033[3m"
    RESET: str = "\033[0m"


class A2AREPL:
    def __init__(self, base_url: str):
        self.base_url: str = base_url
        self.client: ClientFactory = None
        self.httpx_client: httpx.AsyncClient = None
        self.agent_name: str = None
        self.context_id: str = None
        self.format_markdown: bool = True  # Enable markdown formatting by default

    def format_response(self, text: str) -> str:
        """Format response text with basic markdown styling"""
        if not self.format_markdown:
            return text

        # Bold text (**text** -> colored text)
        text = re.sub(r"\*\*(.*?)\*\*", f"{Colors.BOLD}\\1{Colors.RESET}", text)

        # Italic text (*text* -> italic text)
        text = re.sub(r"\*([^*]+)\*", f"{Colors.ITALIC}\\1{Colors.RESET}", text)

        # Code blocks (```code``` -> colored text)
        text = re.sub(
            r"```(.*?)```", f"{Colors.CYAN}\\1{Colors.RESET}", text, flags=re.DOTALL
        )

        # Inline code (`code` -> colored text)
        text = re.sub(r"`([^`]+)`", f"{Colors.CYAN}\\1{Colors.RESET}", text)

        # Headers (## Header -> colored text)
        text = re.sub(
            r"^(#{1,6})\s*(.*?)$",
            f"{Colors.BOLD}\\2{Colors.RESET}",
            text,
            flags=re.MULTILINE,
        )

        # Bullet points (- item -> colored bullet)
        text = re.sub(
            r"^-\s*(.*?)$",
            f"{Colors.GREEN}•{Colors.RESET} \\1",
            text,
            flags=re.MULTILINE,
        )

        return text

    def process_user_input(self, user_input: str) -> str:
        """Process user input to detect dragged file paths and auto-convert to @ syntax"""
        words = user_input.split()
        processed_words = []

        for word in words:
            # Detect absolute paths that look like dragged files
            if (word.startswith('/') or  # Unix/macOS
                (len(word) > 2 and word[1:3] == ':\\') or  # Windows C:\
                word.startswith('~/')):  # Home directory

                # Check if it's actually a file
                expanded_path = os.path.expanduser(word)
                if os.path.isfile(expanded_path):
                    processed_words.append(f"@{word}")
                    print(f"{Colors.DIM}Detected file: {word}{Colors.RESET}")
                else:
                    processed_words.append(word)
            else:
                processed_words.append(word)

        return ' '.join(processed_words)

    def split_text_and_files(self, text: str) -> list[str]:
        """Split text into segments, keeping @file references as separate items"""
        # Use regex split that keeps the delimiters (the @file parts)
        pattern = r'(@[^\s]+)'
        return [segment for segment in re.split(pattern, text) if segment]

    def resolve_file_path(self, file_path: str) -> str | None:
        """Resolve a file path, checking multiple locations"""
        # Expand home directory
        expanded_path = os.path.expanduser(file_path)

        # If it's already absolute and exists, use it
        if os.path.isabs(expanded_path) and os.path.isfile(expanded_path):
            return expanded_path

        # Try relative to current directory
        if os.path.isfile(file_path):
            return os.path.abspath(file_path)

        # Try in uploads directory
        uploads_path = os.path.join(os.getcwd(), 'uploads', file_path)
        if os.path.isfile(uploads_path):
            return uploads_path

        return None

    async def read_file_as_part(self, file_path: str) -> FilePart | None:
        """Read a file and convert it to a FilePart"""
        try:
            resolved_path = self.resolve_file_path(file_path)
            if not resolved_path:
                print(f"{Colors.RED}File not found: {file_path}{Colors.RESET}")
                return None

            # Get file info
            file_name = os.path.basename(resolved_path)
            mime_type, _ = mimetypes.guess_type(resolved_path)
            if not mime_type:
                mime_type = "application/octet-stream"

            # Read and encode file
            with open(resolved_path, 'rb') as f:
                file_data = f.read()
                base64_data = base64.b64encode(file_data).decode('utf-8')

            print(f"{Colors.GREEN}Loaded file: {file_name} ({len(file_data)} bytes, {mime_type}){Colors.RESET}")

            return FilePart(
                kind="file",
                file=FileWithBytes(
                    name=file_name,
                    mime_type=mime_type,
                    bytes=base64_data
                )
            )

        except Exception as e:
            print(f"{Colors.RED}Error reading file {file_path}: {e}{Colors.RESET}")
            return None

    async def initialize(self):
        """Initialize the client by fetching agent card and setting up connection"""
        self.httpx_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

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

    def _debug_print_event(self, event, debug: bool):
        """Print debug information for an event"""
        if debug:
            print()
            print(f"{Colors.YELLOW}DEBUG - Full event{Colors.RESET}")
            pprint(event.__dict__)
            print()

    def _handle_context_id(self, event, debug: bool):
        """Handle context_id storage from server response"""
        if event.context_id and not self.context_id:
            self.context_id = event.context_id
            if debug:
                print(
                    f"{Colors.GREEN}Stored context_id: {self.context_id}{Colors.RESET}"
                )

    def _handle_message_parts(self, event, use_streaming: bool):
        """Handle message parts in the event"""
        for part in event.parts:
            if hasattr(part, "root") and hasattr(part.root, "text"):
                if use_streaming:
                    print()  # Add newline after streaming
                formatted_text = self.format_response(part.root.text)
                print(formatted_text)

    def _handle_artifact(self, artifact, use_streaming: bool):
        """Handle a single artifact"""
        if hasattr(artifact, "data") and hasattr(artifact.data, "text"):
            if use_streaming:
                print(artifact.data.text, end="", flush=True)
            else:
                formatted_text = self.format_response(artifact.data.text)
                print(formatted_text)

    def _handle_tuple_event(self, event, use_streaming: bool):
        """Handle tuple event (task, update_event)"""
        _, update_event = event
        if update_event and hasattr(update_event, "artifacts"):
            for artifact in update_event.artifacts:
                self._handle_artifact(artifact, use_streaming)

    async def send_message(
        self, text: str, use_streaming: bool = False, debug: bool = False
    ):
        """Send a message to the agent"""
        if not self.client:
            raise RuntimeError("Client not initialized. Call initialize() first.")

        # Process input for drag-and-drop file detection
        processed_text = self.process_user_input(text)

        # Split text into segments (text and @file references)
        segments = self.split_text_and_files(processed_text)

        # Create interleaved message parts
        parts = []
        for segment in segments:
            if segment.startswith('@'):
                # This is a file reference - remove @ and create FilePart
                file_path = segment[1:]  # Remove the @ prefix
                file_part = await self.read_file_as_part(file_path)
                if file_part:
                    parts.append(file_part)
            else:
                # This is text - create TextPart (only if non-empty)
                if segment.strip():
                    parts.append(TextPart(text=segment))

        # If no parts were created, add the original text
        if not parts:
            parts.append(TextPart(text=text))

        # Create message with new API
        message = Message(
            message_id=uuid4().hex,
            role="user",  # type: ignore
            parts=parts,  # type: ignore
            context_id=self.context_id,
        )

        try:
            # The new send_message method returns an async iterator
            async for event in self.client.send_message(message):
                self._debug_print_event(event, debug)

                # Handle different event types
                if isinstance(event, Message):
                    self._handle_context_id(event, debug)
                    self._handle_message_parts(event, use_streaming)
                elif isinstance(event, tuple):
                    self._handle_tuple_event(event, use_streaming)

        except Exception as e:
            print(f"{Colors.RED}Error: {e}{Colors.RESET}")
            traceback.print_exc()

    def show_welcome(self):
        """Display welcome banner and commands"""
        agent_display = f" {self.agent_name}" if self.agent_name else ""
        print(f"\n{Colors.BOLD}a2a{agent_display}{Colors.RESET}")
        print(f"{Colors.DIM}> You are connected to an A2A agent{Colors.RESET}")
        print()
        print(
            f"{Colors.DIM}To get started, type a message or try one of these commands:{Colors.RESET}"
        )
        print()
        print(
            f"{Colors.CYAN}/stream{Colors.RESET} {Colors.DIM}- toggle streaming mode{Colors.RESET}"
        )
        print(
            f"{Colors.CYAN}/debug{Colors.RESET}  {Colors.DIM}- toggle debug mode{Colors.RESET}"
        )
        print(
            f"{Colors.CYAN}/format{Colors.RESET} {Colors.DIM}- toggle markdown formatting{Colors.RESET}"
        )
        print(
            f"{Colors.CYAN}/clear{Colors.RESET}  {Colors.DIM}- clear conversation context{Colors.RESET}"
        )
        print(
            f"{Colors.CYAN}/help{Colors.RESET}   {Colors.DIM}- show this help{Colors.RESET}"
        )
        print(
            f"{Colors.CYAN}/quit{Colors.RESET}   {Colors.DIM}- exit the session{Colors.RESET}"
        )
        print()
        print(f"{Colors.DIM}File uploads:{Colors.RESET}")
        print(
            f"{Colors.YELLOW}@filename{Colors.RESET}    {Colors.DIM}- upload file (e.g., 'Analyze @data.csv'){Colors.RESET}"
        )
        print(
            f"{Colors.YELLOW}drag & drop{Colors.RESET}  {Colors.DIM}- drag files from Finder/Explorer into terminal{Colors.RESET}"
        )
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

                if user_input in ["/quit", "/exit"]:
                    print(f"{Colors.DIM}Goodbye!{Colors.RESET}")
                    break
                elif user_input == "/stream":
                    use_streaming = not use_streaming
                    status = (
                        f"{Colors.GREEN}ON{Colors.RESET}"
                        if use_streaming
                        else f"{Colors.DIM}OFF{Colors.RESET}"
                    )
                    print(f"{Colors.DIM}Streaming mode: {status}{Colors.RESET}")
                    continue
                elif user_input == "/debug":
                    debug_mode = not debug_mode
                    status = (
                        f"{Colors.GREEN}ON{Colors.RESET}"
                        if debug_mode
                        else f"{Colors.DIM}OFF{Colors.RESET}"
                    )
                    print(f"{Colors.DIM}Debug mode: {status}{Colors.RESET}")
                    continue
                elif user_input == "/format":
                    self.format_markdown = not self.format_markdown
                    status = (
                        f"{Colors.GREEN}ON{Colors.RESET}"
                        if self.format_markdown
                        else f"{Colors.DIM}OFF{Colors.RESET}"
                    )
                    print(f"{Colors.DIM}Markdown formatting: {status}{Colors.RESET}")
                    continue
                elif user_input == "/clear":
                    self.context_id = None
                    print(f"{Colors.DIM}Conversation context cleared{Colors.RESET}")
                    continue
                elif user_input == "/help":
                    print(
                        f"{Colors.CYAN}/stream{Colors.RESET} {Colors.DIM}- toggle streaming mode{Colors.RESET}"
                    )
                    print(
                        f"{Colors.CYAN}/debug{Colors.RESET}  {Colors.DIM}- toggle debug mode{Colors.RESET}"
                    )
                    print(
                        f"{Colors.CYAN}/format{Colors.RESET} {Colors.DIM}- toggle markdown formatting{Colors.RESET}"
                    )
                    print(
                        f"{Colors.CYAN}/clear{Colors.RESET}  {Colors.DIM}- clear conversation context{Colors.RESET}"
                    )
                    print(
                        f"{Colors.CYAN}/help{Colors.RESET}   {Colors.DIM}- show this help{Colors.RESET}"
                    )
                    print(
                        f"{Colors.CYAN}/quit{Colors.RESET}   {Colors.DIM}- exit the session{Colors.RESET}"
                    )
                    print()
                    print(f"{Colors.DIM}File uploads:{Colors.RESET}")
                    print(
                        f"{Colors.YELLOW}@filename{Colors.RESET}    {Colors.DIM}- upload file (e.g., 'Analyze @data.csv'){Colors.RESET}"
                    )
                    print(
                        f"{Colors.YELLOW}drag & drop{Colors.RESET}  {Colors.DIM}- drag files from Finder/Explorer into terminal{Colors.RESET}"
                    )
                    continue

                await self.send_message(user_input, use_streaming, debug_mode)
                print()

            except KeyboardInterrupt:
                print(f"\n{Colors.DIM}Goodbye!{Colors.RESET}")
                break
            except Exception as e:
                print(f"{Colors.RED}Error: {e}{Colors.RESET}")
                traceback.print_exc()

    async def cleanup(self):
        """Clean up resources"""
        if self.httpx_client:
            await self.httpx_client.aclose()


async def main() -> None:
    parser = argparse.ArgumentParser(description="A2A Client REPL")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "9999")),
        help="Port to connect to (default: 9999 or PORT env var)",
    )

    args = parser.parse_args()
    base_url = f"http://localhost:{args.port}"

    repl = A2AREPL(base_url)

    try:
        await repl.run_repl()
    finally:
        await repl.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
