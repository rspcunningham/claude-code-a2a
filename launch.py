import argparse
import sys
import os
import time
import secrets
from pathlib import Path
from python_on_whales import docker


def generate_workspace_id():
    """Generate a unique workspace ID"""
    random_id = secrets.token_hex(6)  # 12 hex characters
    return f"ws_{random_id}"


def get_workspace_path(workspace_id):
    """Get the host path for a workspace"""
    return Path.cwd() / "workspace" / workspace_id


def get_running_agents():
    """Get list of running claude agent containers"""
    try:
        containers = docker.container.list(filters={"name": "claude-agent"})
        agents = []

        for container in containers:
            # Extract workspace ID from container name
            workspace_id = "unknown"

            # Check for new naming scheme: claude-agent-ws_123_abc
            if container.name.startswith("claude-agent-ws_"):
                workspace_id = container.name.replace("claude-agent-", "")
            # Check for old docker-compose naming
            elif container.name.startswith("claude-code-a2a-claude-agent"):
                # Try to extract from volume mounts
                try:
                    inspect = docker.container.inspect(container.name)
                    for mount in inspect.mounts:
                        if mount.destination == "/workspace":
                            workspace_path = Path(mount.source)
                            workspace_id = workspace_path.name
                            break
                except Exception:
                    pass

            # Get port mapping
            port_info = "No port"
            try:
                if container.network_settings and container.network_settings.ports:
                    ports = container.network_settings.ports.get("9999/tcp")
                    if ports and ports[0]:
                        port_info = f"localhost:{ports[0]['HostPort']}"
            except Exception:
                pass

            agents.append(
                {
                    "container": container.name,
                    "workspace": workspace_id,
                    "port": port_info,
                    "status": container.state.status,
                }
            )

        return agents
    except Exception as e:
        print(f"Error getting running agents: {e}", file=sys.stderr)
        return []


def get_all_agents():
    """Get list of all claude agent containers (running and stopped)"""
    try:
        containers = docker.container.list(all=True, filters={"name": "claude-agent"})
        agents = []

        for container in containers:
            # Extract workspace ID from container name
            workspace_id = "unknown"

            # Check for new naming scheme: claude-agent-ws_123_abc
            if container.name.startswith("claude-agent-ws_"):
                workspace_id = container.name.replace("claude-agent-", "")
            # Check for old docker-compose naming
            elif container.name.startswith("claude-code-a2a-claude-agent"):
                # Try to extract from volume mounts
                try:
                    inspect = docker.container.inspect(container.name)
                    for mount in inspect.mounts:
                        if mount.destination == "/workspace":
                            workspace_path = Path(mount.source)
                            workspace_id = workspace_path.name
                            break
                except Exception:
                    pass

            # Get port mapping
            port_info = "No port"
            try:
                if container.network_settings and container.network_settings.ports:
                    ports = container.network_settings.ports.get("9999/tcp")
                    if ports and ports[0]:
                        port_info = f"localhost:{ports[0]['HostPort']}"
            except Exception:
                pass

            agents.append(
                {
                    "container": container.name,
                    "workspace": workspace_id,
                    "port": port_info,
                    "status": container.state.status,
                }
            )

        return agents
    except Exception as e:
        print(f"Error getting all agents: {e}", file=sys.stderr)
        return []


def print_agents_status(agents, title="Running Claude Agents"):
    """Print formatted table of agent status"""
    if not agents:
        print(f"{title}: None")
        return

    print(f"\n{title}:")
    print(
        "┌─────────────────────────────────┬──────────────────────┬─────────────────┬─────────────┐"
    )
    print(
        "│ Container                       │ Workspace            │ Host Port       │ Status      │"
    )
    print(
        "├─────────────────────────────────┼──────────────────────┼─────────────────┼─────────────┤"
    )

    for agent in agents:
        container = agent["container"][:31]  # Truncate long names
        workspace = agent["workspace"][:20]  # Increased from 12 to 20
        port = agent["port"][:15]
        status = agent["status"][:11]
        print(f"│ {container:<31} │ {workspace:<20} │ {port:<15} │ {status:<11} │")

    print(
        "└─────────────────────────────────┴──────────────────────┴─────────────────┴─────────────┘"
    )


def list_available_workspaces():
    """List all available workspace directories"""
    workspace_dir = Path.cwd() / "workspace"
    if not workspace_dir.exists():
        print("No workspace directory found.")
        return []

    workspaces = []
    for item in workspace_dir.iterdir():
        if item.is_dir() and item.name.startswith("ws_"):
            workspaces.append(
                {
                    "id": item.name,
                    "path": str(item),
                    "size": sum(
                        f.stat().st_size for f in item.rglob("*") if f.is_file()
                    ),
                }
            )

    return workspaces


def print_workspaces(workspaces):
    """Print formatted table of available workspaces"""
    if not workspaces:
        print("No workspaces found.")
        return

    print("\nAvailable Workspaces:")
    print(
        "┌──────────────────┬─────────────────────────────────────────┬──────────────┐"
    )
    print(
        "│ Workspace ID     │ Path                                    │ Size (bytes) │"
    )
    print(
        "├──────────────────┼─────────────────────────────────────────┼──────────────┤"
    )

    for ws in workspaces:
        ws_id = ws["id"][:16]
        path = ws["path"][:39]
        size = f"{ws['size']:,}"[:12]
        print(f"│ {ws_id:<16} │ {path:<39} │ {size:>12} │")

    print(
        "└──────────────────┴─────────────────────────────────────────┴──────────────┘"
    )


def launch_container(workspace_id, rebuild=False):
    """Launch a new container with the specified workspace"""
    workspace_path = get_workspace_path(workspace_id)

    # Create workspace directory if it doesn't exist
    workspace_path.mkdir(parents=True, exist_ok=True)

    container_name = f"claude-agent-{workspace_id}"

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
            # Check that workspace directory exists
            if not workspace_path.exists():
                print(
                    f"Error: Workspace directory '{workspace_path}' not found for existing container."
                )
                print(
                    "The workspace may have been deleted. Use --cleanup to remove orphaned containers."
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
        print(f"Workspace path: {workspace_path.absolute()}")
        print(f"Container name: {container_name}")

        # Ensure heartbeat-logger is running first
        print("Ensuring heartbeat-logger is running...")
        os.environ["WORKSPACE_PATH"] = "/tmp"  # Set dummy value for build
        docker.compose.up("heartbeat-logger", detach=True)

        # Get the image name from docker-compose
        project_name = "claude-code-a2a"  # Based on your directory name
        image_name = f"{project_name}-claude-agent"

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
            docker.build(".", tags=[image_name])
        else:
            print(f"Using existing image: {image_name}")

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
            volumes=[(str(workspace_path.absolute()), "/workspace")],
            publish=[
                (0, 9999)
            ],  # Random host port mapping (0 means any available port)
            envs=env_vars,
            restart="unless-stopped",
            networks=["claude-code-a2a_default"],  # Connect to compose network
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
    container_name = f"claude-agent-{workspace_id}"
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
    agents = get_running_agents()
    for agent in agents:
        if agent["workspace"] == workspace_id:
            try:
                docker.container.stop(agent["container"])
                print(f"✓ Stopped container: {agent['container']}")
                return True
            except Exception as e:
                print(
                    f"Error stopping container {agent['container']}: {e}",
                    file=sys.stderr,
                )
                return False

    print(f"No running container found for workspace: {workspace_id}")
    return False


def cleanup_unused_workspaces():
    """Remove stopped containers and unused workspace directories"""
    import shutil

    cleanup_actions = []

    # 1. Find stopped containers
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
    except Exception as e:
        print(f"Error finding stopped containers: {e}")

    # 2. Find unused workspace directories
    workspaces = list_available_workspaces()
    if workspaces:
        # Get all workspace IDs that have any container (running or stopped)
        try:
            all_containers = docker.container.list(
                all=True, filters={"name": "claude-agent"}
            )
            container_workspaces = set()
            for container in all_containers:
                if container.name.startswith("claude-agent-ws_"):
                    workspace_id = container.name.replace("claude-agent-", "")
                    container_workspaces.add(workspace_id)
        except:
            container_workspaces = set()

        # Find workspaces with no containers at all
        for ws in workspaces:
            if ws["id"] not in container_workspaces:
                cleanup_actions.append(
                    {
                        "type": "workspace",
                        "name": ws["id"],
                        "path": ws["path"],
                        "size": ws["size"],
                        "action": f"Delete workspace directory: {ws['id']} ({ws['size']:,} bytes)",
                    }
                )

    if not cleanup_actions:
        print("Nothing to cleanup - no stopped containers or unused workspaces found.")
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
            elif item["type"] == "workspace":
                shutil.rmtree(item["path"])
                print(f"✓ Deleted workspace: {item['name']}")
            success_count += 1
        except Exception as e:
            print(f"✗ Failed to cleanup {item['name']}: {e}")

    print(
        f"\n✓ Cleanup complete: {success_count}/{len(cleanup_actions)} items cleaned up."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Launch and manage claude-agent instances",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./launch.py --fresh                    Launch new container with fresh workspace
  ./launch.py --fresh --rebuild          Launch with fresh workspace and rebuild image
  ./launch.py --workspace ws_123_abc     Launch container with existing workspace
  ./launch.py --status                   Show running containers only
  ./launch.py --list-workspaces          Show available workspaces
  ./launch.py --stop ws_123_abc          Stop container (keeps container and workspace)
  ./launch.py --cleanup                  Remove stopped containers and unused workspaces

Container Lifecycle:
  - Fresh launch creates new workspace + container
  - Stop only stops the container (can restart later)
  - Cleanup removes stopped containers + orphaned workspace dirs
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
        help="List available workspace directories",
    )
    group.add_argument(
        "--stop",
        type=str,
        metavar="WORKSPACE_ID",
        help="Stop container for specified workspace",
    )
    group.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove stopped containers and unused workspace directories",
    )

    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force rebuild of Docker image before launching",
    )

    args = parser.parse_args()

    # Always show current status first (except for --status only)
    if not args.status:
        current_agents = get_running_agents()
        print_agents_status(current_agents, "Current Running Agents")

    if args.status:
        agents = get_all_agents()
        print_agents_status(agents, "All Claude Agents (Running & Stopped)")

    elif args.list_workspaces:
        workspaces = list_available_workspaces()
        print_workspaces(workspaces)

    elif args.stop:
        success = stop_container(args.stop)
        sys.exit(0 if success else 1)

    elif args.cleanup:
        cleanup_unused_workspaces()

    elif args.fresh:
        workspace_id = generate_workspace_id()
        success = launch_container(workspace_id, rebuild=args.rebuild)

        if success:
            print("\n" + "=" * 50)
            agents = get_running_agents()
            print_agents_status(agents, "All Running Agents")

        sys.exit(0 if success else 1)

    elif args.workspace:
        workspace_path = get_workspace_path(args.workspace)
        if not workspace_path.exists():
            print(
                f"Error: Workspace '{args.workspace}' does not exist.", file=sys.stderr
            )
            print(f"Expected path: {workspace_path.absolute()}", file=sys.stderr)
            sys.exit(1)

        success = launch_container(args.workspace, rebuild=args.rebuild)

        if success:
            print("\n" + "=" * 50)
            agents = get_running_agents()
            print_agents_status(agents, "All Running Agents")

        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
