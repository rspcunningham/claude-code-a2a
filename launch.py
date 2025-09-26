import argparse
import sys
import os
import time
import secrets
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from python_on_whales import docker

# Configuration constants
PROJECT_NAME = "fleet-of-agents"
NETWORK_NAME = "fleet-of-agents_agent-network"
AGENT_NAME = "claude-agent"


@dataclass
class Agent:
    container_name: str
    workspace_id: str
    port_info: str
    status: str


@dataclass
class Volume:
    workspace_id: str
    volume_name: str
    created: str


def generate_workspace_id() -> str:
    """Generate a unique workspace ID"""
    random_id = secrets.token_hex(6)  # 12 hex characters
    return f"ws_{random_id}"


def extract_workspace_id(container) -> str:
    """Extract workspace ID from container name or volume mounts"""
    # Check for new naming scheme: claude-agent-ws_123_abc
    if container.name.startswith(f"{AGENT_NAME}-ws_"):
        return container.name.replace(f"{AGENT_NAME}-", "")

    # Check for old docker-compose naming
    if container.name.startswith("claude-code-a2a-claude-agent"):
        try:
            inspect = docker.container.inspect(container.name)
            for mount in inspect.mounts:
                if mount.destination == "/workspace" and mount.type == "volume":
                    volume_name = mount.name
                    if volume_name.startswith(f"{PROJECT_NAME}-"):
                        return volume_name.replace(f"{PROJECT_NAME}-", "")
        except Exception:
            pass

    return "unknown"


def get_port_info(container) -> str:
    """Extract port information from container"""
    try:
        if container.network_settings and container.network_settings.ports:
            ports = container.network_settings.ports.get("9999/tcp")
            if ports and ports[0]:
                return f"localhost:{ports[0]['HostPort']}"
    except Exception:
        pass
    return "No port"


def get_agents(running_only: bool = True) -> List[Agent]:
    """Get list of claude agent containers"""
    try:
        containers = docker.container.list(all=not running_only, filters={"name": AGENT_NAME})
        return [
            Agent(
                container_name=container.name,
                workspace_id=extract_workspace_id(container),
                port_info=get_port_info(container),
                status=container.state.status
            )
            for container in containers
        ]
    except Exception as e:
        print(f"Error getting agents: {e}", file=sys.stderr)
        return []


def print_table(headers: List[str], rows: List[List[str]], title: str = ""):
    """Generic table printer"""
    if not rows:
        print(f"{title}: None" if title else "No data found")
        return

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    if title:
        print(f"\n{title}:")

    # Top border
    print("┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐")

    # Headers
    print("│" + "│".join(f" {h:<{col_widths[i]}} " for i, h in enumerate(headers)) + "│")

    # Separator
    print("├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤")

    # Data rows
    for row in rows:
        print("│" + "│".join(f" {cell:<{col_widths[i]}} " for i, cell in enumerate(row)) + "│")

    # Bottom border
    print("└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘")


def print_agents_status(agents: List[Agent], title: str = "Running Claude Agents"):
    """Print formatted table of agent status"""
    headers = ["Container", "Workspace", "Host Port", "Status"]
    rows = [
        [agent.container_name[:31], agent.workspace_id[:20], agent.port_info[:15], agent.status[:11]]
        for agent in agents
    ]
    print_table(headers, rows, title)


def list_available_volumes() -> List[Volume]:
    """List all available workspace volumes"""
    try:
        all_volumes = docker.volume.list()
        project_volumes = [v for v in all_volumes if v.name.startswith(f"{PROJECT_NAME}-ws_")]

        volumes = [
            Volume(
                workspace_id=volume.name.replace(f"{PROJECT_NAME}-", ""),
                volume_name=volume.name,
                created=volume.created_at if hasattr(volume, 'created_at') else "Unknown"
            )
            for volume in project_volumes
        ]

        return sorted(volumes, key=lambda x: x.workspace_id)
    except Exception as e:
        print(f"Error listing volumes: {e}")
        return []


def print_volumes(volumes: List[Volume], title: str = "Available Workspace Volumes"):
    """Print formatted table of available workspace volumes"""
    headers = ["Workspace ID", "Volume Name", "Created"]
    rows = [
        [vol.workspace_id[:16], vol.volume_name[:39], str(vol.created)[:12]]
        for vol in volumes
    ]
    print_table(headers, rows, title)


def launch_container(workspace_id, rebuild=False, template=None):
    """Launch a new container with the specified workspace"""
    volume_name = f"{PROJECT_NAME}-{workspace_id}"
    container_name = f"{AGENT_NAME}-{workspace_id}"

    # Check if container already exists
    existing_container = None
    try:
        existing_container = docker.container.inspect(container_name)
    except Exception:
        pass

    if existing_container:
        if existing_container.state.running:
            print(f"Container {container_name} is already running!")
            return True
        else:
            # Check that workspace volume exists
            try:
                docker.volume.inspect(volume_name)
            except Exception:
                print(
                    f"Error: Workspace volume '{volume_name}' not found for existing container."
                )
                print(
                    "The volume may have been deleted. Use --cleanup to remove orphaned containers."
                )
                return False

            print(f"Resuming stopped container {container_name}...")
            docker.container.start(container_name)

            # Give it a moment to start
            time.sleep(2)

            # Get port mapping
            container_info = docker.container.inspect(container_name)
            port_info = "No port"
            try:
                if (
                    container_info.network_settings
                    and container_info.network_settings.ports
                ):
                    ports = container_info.network_settings.ports.get("9999/tcp")
                    if ports and ports[0]:
                        port_info = f"localhost:{ports[0]['HostPort']}"
            except:
                pass

            print(f"✓ Container resumed: {container_name} -> {port_info}")
            return True

    try:
        print(f"\nLaunching new container with workspace: {workspace_id}")
        print(f"Volume name: {volume_name}")
        print(f"Container name: {container_name}")

        # Ensure heartbeat-logger is running first
        print("Ensuring heartbeat-logger is running...")
        os.environ["WORKSPACE_PATH"] = "/tmp"  # Set dummy value for build
        docker.compose.up("heartbeat-logger", detach=True)

        # Get the image name - use template if specified
        if template:
            # Validate template exists
            available_templates = [t["name"] for t in get_available_templates()]
            if template not in available_templates:
                print(f"Error: Template '{template}' not found.")
                print(f"Available templates: {', '.join(available_templates)}")
                return False
            image_name = f"{PROJECT_NAME}-{AGENT_NAME}:template-{template}"
        else:
            image_name = f"{PROJECT_NAME}-{AGENT_NAME}:template-empty"

        # Check if image exists, build only if needed or forced
        image_exists = False
        try:
            docker.image.inspect(image_name)
            image_exists = True
        except Exception:
            pass

        if not image_exists or rebuild:
            if rebuild:
                print("Rebuilding claude-agent image...")
            else:
                print("Image not found, building claude-agent image...")
            docker.build(".", tags=[image_name], load=True)
        else:
            print(f"Using existing image: {image_name}")

        # Create named volume if it doesn't exist
        try:
            docker.volume.inspect(volume_name)
            print(f"Using existing volume: {volume_name}")
        except Exception:
            print(f"Creating new volume: {volume_name}")
            docker.volume.create(volume_name)

        # Load .env file manually and merge with environment
        env_vars = {"HEARTBEAT_URL": "http://heartbeat-logger:8080/heartbeat"}
        try:
            with open(".env", "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key] = value
        except FileNotFoundError:
            pass  # .env file is optional

        # Launch container directly with docker run
        docker.container.run(
            image_name,
            name=container_name,
            detach=True,
            volumes=[(volume_name, "/workspace")],
            publish=[
                (0, 9999)
            ],  # Random host port mapping (0 means any available port)
            envs=env_vars,
            restart="unless-stopped",
            networks=[NETWORK_NAME],  # Connect to compose network
            labels={
                "com.docker.compose.project": PROJECT_NAME,
                "com.docker.compose.service": AGENT_NAME,
            },
        )

        # Give it a moment to start
        time.sleep(2)

        # Get port mapping
        container_info = docker.container.inspect(container_name)
        port_info = "No port"
        try:
            if (
                container_info.network_settings
                and container_info.network_settings.ports
            ):
                ports = container_info.network_settings.ports.get("9999/tcp")
                if ports and ports[0]:
                    port_info = f"localhost:{ports[0]['HostPort']}"

        except Exception:
            pass

        print(f"✓ Container started: {container_name} -> {port_info}")

    except Exception as e:
        print(f"Error launching container: {e}", file=sys.stderr)
        return False

    return True


def stop_container(workspace_id):
    """Stop container associated with workspace"""
    # Try direct container name first (new scheme)
    container_name = f"{AGENT_NAME}-{workspace_id}"
    try:
        container = docker.container.inspect(container_name)
        if container.state.running:
            docker.container.stop(container_name)
            print(f"✓ Stopped container: {container_name}")
            return True
        else:
            print(f"Container {container_name} is already stopped")
            return True
    except Exception:
        pass

    # Fallback to searching through running agents
    agents = get_agents(running_only=True)
    for agent in agents:
        if agent.workspace_id == workspace_id:
            try:
                docker.container.stop(agent.container_name)
                print(f"✓ Stopped container: {agent.container_name}")
                return True
            except Exception as e:
                print(
                    f"Error stopping container {agent.container_name}: {e}",
                    file=sys.stderr,
                )
                return False

    print(f"No running container found for workspace: {workspace_id}")
    return False


def stop_all_containers():
    """Stop all running claude agent containers"""
    agents = get_agents(running_only=True)

    if not agents:
        print("No running containers found")
        return True

    print(f"Found {len(agents)} running container(s) to stop:")
    for agent in agents:
        print(f"  - {agent.container_name} ({agent.workspace_id})")

    confirm = input(f"\nStop all {len(agents)} container(s)? (y/N): ")
    if confirm.lower() != "y":
        print("Stop cancelled.")
        return False

    success_count = 0
    for agent in agents:
        try:
            docker.container.stop(agent.container_name)
            print(f"✓ Stopped container: {agent.container_name}")
            success_count += 1
        except Exception as e:
            print(f"✗ Failed to stop {agent.container_name}: {e}")

    print(f"\n✓ Stop complete: {success_count}/{len(agents)} containers stopped")
    return success_count == len(agents)


def cleanup_unused_workspaces():
    """Remove stopped containers and their associated named volumes"""
    cleanup_actions = []
    stopped_container_volumes = set()

    # 1. Find stopped containers and their volumes
    try:
        all_containers = docker.container.list(
            all=True, filters={"name": "claude-agent"}
        )
        stopped_containers = [c for c in all_containers if not c.state.running]

        for container in stopped_containers:
            cleanup_actions.append(
                {
                    "type": "container",
                    "name": container.name,
                    "action": f"Remove stopped container: {container.name}",
                }
            )

            # Track volume name of stopped container
            if container.name.startswith("claude-agent-ws_"):
                workspace_id = container.name.replace("claude-agent-", "")
                volume_name = f"{PROJECT_NAME}-{workspace_id}"
                stopped_container_volumes.add(volume_name)

    except Exception as e:
        print(f"Error finding stopped containers: {e}")

    # 2. Find volumes to remove
    try:
        # Get all volumes that belong to our project
        all_volumes = docker.volume.list()
        project_volumes = [v for v in all_volumes if v.name.startswith(f"{PROJECT_NAME}-ws_")]

        # Get volume names that have running containers (should be kept)
        running_containers = [c for c in docker.container.list(filters={"name": "claude-agent"})]
        running_container_volumes = set()
        for container in running_containers:
            if container.name.startswith("claude-agent-ws_"):
                workspace_id = container.name.replace("claude-agent-", "")
                volume_name = f"{PROJECT_NAME}-{workspace_id}"
                running_container_volumes.add(volume_name)

        # Remove volumes that belong to stopped containers OR have no containers at all
        for volume in project_volumes:
            if (volume.name in stopped_container_volumes or
                volume.name not in running_container_volumes):
                cleanup_actions.append(
                    {
                        "type": "volume",
                        "name": volume.name,
                        "action": f"Delete volume: {volume.name}",
                    }
                )

    except Exception as e:
        print(f"Error finding volumes: {e}")

    if not cleanup_actions:
        print("Nothing to cleanup - no stopped containers or unused volumes found.")
        return

    print(f"\nFound {len(cleanup_actions)} item(s) to cleanup:")
    for item in cleanup_actions:
        print(f"  - {item['action']}")

    confirm = input("\nProceed with cleanup? (y/N): ")
    if confirm.lower() != "y":
        print("Cleanup cancelled.")
        return

    # Execute cleanup
    success_count = 0
    for item in cleanup_actions:
        try:
            if item["type"] == "container":
                docker.container.remove(item["name"])
                print(f"✓ Removed container: {item['name']}")
            elif item["type"] == "volume":
                docker.volume.remove(item["name"])
                print(f"✓ Deleted volume: {item['name']}")
            success_count += 1
        except Exception as e:
            print(f"✗ Failed to cleanup {item['name']}: {e}")

    print(
        f"\n✓ Cleanup complete: {success_count}/{len(cleanup_actions)} items cleaned up."
    )


def get_available_templates():
    """Get list of available templates from filesystem"""
    templates_dir = Path.cwd() / "templates"
    if not templates_dir.exists():
        return []

    templates = []
    for item in templates_dir.iterdir():
        if item.is_dir():
            # Check if it has a README.md to get description
            readme_path = item / "README.md"
            description = "No description available"
            if readme_path.exists():
                try:
                    content = readme_path.read_text()
                    # Get first line after the title
                    lines = content.split("\n")
                    for line in lines[1:]:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            description = line
                            break
                except:
                    pass

            templates.append(
                {"name": item.name, "description": description, "path": str(item)}
            )

    # Add the built-in empty template
    templates.append(
        {
            "name": "empty",
            "description": "Clean workspace with no pre-installed packages",
            "path": "built-in",
        }
    )

    return sorted(templates, key=lambda x: x["name"])


def list_templates():
    """List available workspace templates"""
    templates = get_available_templates()
    headers = ["Template", "Description"]
    rows = [
        [template["name"][:14], template["description"][:56]]
        for template in templates
    ]
    print_table(headers, rows, "Available Workspace Templates")


def build_templates():
    """Build all template Docker images"""
    templates = get_available_templates()

    print("Building template images...")

    for template in templates:
        template_name = template["name"]
        print(f"\nBuilding template: {template_name}")

        try:
            # Build the specific template stage
            docker.build(
                ".",
                tags=[f"{PROJECT_NAME}-{AGENT_NAME}:template-{template_name}"],
                target=f"template-{template_name}",
                load=True,
            )
            print(f"✓ Built template: {template_name}")
        except Exception as e:
            print(f"✗ Failed to build template {template_name}: {e}")

    print(f"\n✓ Template build complete!")


def main():
    parser = argparse.ArgumentParser(
        description="Launch and manage claude-agent instances",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./launch.py --fresh                    Launch new container with fresh workspace volume
  ./launch.py --fresh --template python-ml   Launch with Python ML template
  ./launch.py --fresh --rebuild          Launch with fresh workspace and rebuild image
  ./launch.py --workspace ws_123_abc     Launch container with existing workspace volume
  ./launch.py --status                   Show running containers only
  ./launch.py --list-workspaces          Show available workspace volumes
  ./launch.py --stop ws_123_abc          Stop container (keeps container and volume)
  ./launch.py --stop-all                 Stop all running containers
  ./launch.py --kill-all                 Stop all containers and cleanup volumes
  ./launch.py --cleanup                  Remove stopped containers and unused volumes

Template Management:
  ./launch.py --list-templates           Show available workspace templates
  ./launch.py --build-templates          Build all template Docker images

Container Lifecycle:
  - Fresh launch creates new workspace volume + container
  - Stop only stops the container (can restart later)
  - Cleanup removes stopped containers + orphaned workspace volumes
  - Templates provide pre-configured development environments
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--fresh", action="store_true", help="Launch new container with fresh workspace"
    )
    group.add_argument(
        "--workspace", type=str, help="Launch container with existing workspace ID"
    )
    group.add_argument(
        "--status", action="store_true", help="Show running containers only (no launch)"
    )
    group.add_argument(
        "--list-workspaces",
        action="store_true",
        help="List available workspace volumes",
    )
    group.add_argument(
        "--stop",
        type=str,
        metavar="WORKSPACE_ID",
        help="Stop container for specified workspace (or use --stop-all for all containers)",
    )
    group.add_argument(
        "--stop-all",
        action="store_true",
        help="Stop all running claude agent containers",
    )
    group.add_argument(
        "--kill-all",
        action="store_true",
        help="Stop all containers and cleanup (equivalent to --stop-all + --cleanup)",
    )
    group.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove stopped containers and unused workspace volumes",
    )
    group.add_argument(
        "--list-templates",
        action="store_true",
        help="List available workspace templates",
    )
    group.add_argument(
        "--build-templates",
        action="store_true",
        help="Build all template Docker images",
    )

    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force rebuild of Docker image before launching",
    )
    parser.add_argument(
        "--template",
        type=str,
        help="Use a workspace template (empty, python-ml, nextjs, data-science)",
    )

    args = parser.parse_args()

    # Always show current status first (except for --status only)
    if not args.status:
        current_agents = get_agents(running_only=True)
        print_agents_status(current_agents, "Current Running Agents")

    if args.status:
        agents = get_agents(running_only=False)
        print_agents_status(agents, "All Claude Agents (Running & Stopped)")

    elif args.list_workspaces:
        volumes = list_available_volumes()
        print_volumes(volumes)

    elif args.stop:
        success = stop_container(args.stop)
        sys.exit(0 if success else 1)

    elif args.stop_all:
        success = stop_all_containers()
        sys.exit(0 if success else 1)

    elif args.kill_all:
        print("=== KILL ALL: Stopping all containers and cleaning up ===\n")

        # Step 1: Stop all containers
        print("Step 1: Stopping all running containers...")
        stop_success = stop_all_containers()

        if not stop_success:
            print("Warning: Some containers failed to stop, but continuing with cleanup...")

        print("\nStep 2: Cleaning up stopped containers and unused volumes...")
        cleanup_unused_workspaces()

        print(f"\n{'='*60}")
        print("✓ Kill-all complete: All containers stopped and cleaned up")
        sys.exit(0)

    elif args.cleanup:
        cleanup_unused_workspaces()

    elif args.list_templates:
        list_templates()

    elif args.build_templates:
        build_templates()

    elif args.fresh:
        workspace_id = generate_workspace_id()
        success = launch_container(
            workspace_id, rebuild=args.rebuild, template=args.template
        )

        if success:
            print("\n" + "=" * 50)
            agents = get_agents(running_only=True)
            print_agents_status(agents, "All Running Agents")

        sys.exit(0 if success else 1)

    elif args.workspace:
        # Check if volume exists for the workspace
        volume_name = f"{PROJECT_NAME}-{args.workspace}"
        try:
            docker.volume.inspect(volume_name)
        except Exception:
            print(
                f"Error: Workspace volume '{volume_name}' does not exist.", file=sys.stderr
            )
            print(f"Use --list-workspaces to see available workspaces.", file=sys.stderr)
            sys.exit(1)

        success = launch_container(args.workspace, rebuild=args.rebuild)

        if success:
            print("\n" + "=" * 50)
            agents = get_agents(running_only=True)
            print_agents_status(agents, "All Running Agents")

        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
