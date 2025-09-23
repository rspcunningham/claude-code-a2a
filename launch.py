#!/usr/bin/env python3

import argparse
import sys
import uuid
from python_on_whales import docker

def generate_workspace_id():
    """Generate a short workspace ID like ws_a1b2c3d4"""
    short_uuid = str(uuid.uuid4())[:8]
    return f"ws_{short_uuid}"

def check_workspace_in_use(workspace_id):
    """Check if workspace is already in use by a running container"""
    try:
        containers = docker.ps(filters={"label": f"workspace.id={workspace_id}"})
        return len(containers) > 0
    except Exception:
        return False

def ensure_heartbeat_logger():
    """Ensure heartbeat logger is running"""
    try:
        # Check if heartbeat logger is already running
        containers = docker.ps(filters={"name": "heartbeat-logger"})
        if len(containers) > 0:
            return True

        # Launch heartbeat logger
        docker.run(
            image="claude-code-sdk-claude-agent",
            name="heartbeat-logger",
            command=["uv", "run", "python", "heartbeat_receiver.py"],
            envs={"HEARTBEAT_PORT": "8080"},
            publish=[("8080",)],
            detach=True,
            remove=False,
            restart="unless-stopped"
        )
        return True
    except Exception as e:
        print(f"Error launching heartbeat logger: {e}", file=sys.stderr)
        return False

def cleanup_existing_container(container_name):
    """Remove existing container with the same name if it exists"""
    try:
        # Check if container exists (running or stopped)
        containers = docker.ps(all=True, filters={"name": f"^{container_name}$"})
        if len(containers) > 0:
            # Stop and remove the existing container
            docker.remove(container_name, force=True)
            return True
    except Exception:
        # Container doesn't exist, which is fine
        pass
    return False

def launch_container(workspace_id, container_name):
    """Launch a single container with specified workspace"""
    # Check if workspace is already in use
    if check_workspace_in_use(workspace_id):
        print(f"Error: workspace {workspace_id} is already in use", file=sys.stderr)
        return None

    # Clean up any existing container with the same name
    if cleanup_existing_container(container_name):
        print(f"Removed existing container: {container_name}")

    try:
        # Create volume if it doesn't exist
        try:
            docker.volume.inspect(workspace_id)
        except:
            docker.volume.create(workspace_id)

        # Launch container with workspace volume and label
        container = docker.run(
            image="claude-code-sdk-claude-agent",
            name=container_name,
            volumes=[(workspace_id, "/workspace")],
            labels={"workspace.id": workspace_id},
            envs={"HEARTBEAT_URL": "http://heartbeat-logger:8080/heartbeat"},
            env_files=[".env"],
            publish=[("9999",)],  # Random host port
            detach=True,
            remove=False,
            restart="unless-stopped",
            link=["heartbeat-logger"]
        )

        # Get the assigned port
        container_info = docker.container.inspect(container.name)
        if container_info.network_settings and container_info.network_settings.ports:
            port_mapping = container_info.network_settings.ports.get("9999/tcp")
            if port_mapping and port_mapping[0]:
                host_port = port_mapping[0]["HostPort"]
                return f"localhost:{host_port}"
        return "(port not found)"

    except Exception as e:
        print(f"Error launching container {container_name}: {e}", file=sys.stderr)
        return None

def stop_all_agents():
    """Stop and remove all claude-agent containers"""
    try:
        # Get all claude-agent containers (running and stopped)
        containers = docker.ps(all=True, filters={"name": "claude-agent-"})

        if len(containers) == 0:
            print("No claude-agent containers found")
            return

        print(f"Stopping and removing {len(containers)} claude-agent containers...")

        container_names = [container.name for container in containers]

        # Stop and remove containers
        for name in container_names:
            try:
                docker.remove(name, force=True)
                print(f"Removed: {name}")
            except Exception as e:
                print(f"Warning: Could not remove {name}: {e}")

        print("All claude-agent containers stopped and removed")

    except Exception as e:
        print(f"Error stopping containers: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Launch claude-agent instances with workspace management",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--fresh',
        type=int,
        default=0,
        help='Number of fresh workspace instances to launch (default: 0)'
    )
    parser.add_argument(
        '--workspace-ids',
        type=str,
        help='Comma-separated list of existing workspace IDs to restore'
    )
    parser.add_argument(
        '--stop',
        action='store_true',
        help='Stop and remove all claude-agent containers'
    )

    args = parser.parse_args()

    # Handle stop command
    if args.stop:
        stop_all_agents()
        return

    # If no arguments provided, default to 1 fresh instance
    if args.fresh == 0 and not args.workspace_ids:
        args.fresh = 1

    workspace_ids = []
    if args.workspace_ids:
        workspace_ids = [ws.strip() for ws in args.workspace_ids.split(',')]

    total_containers = args.fresh + len(workspace_ids)

    if total_containers == 0:
        print("No containers to launch", file=sys.stderr)
        sys.exit(1)

    print(f"Launching {total_containers} claude-agent instances...")

    # Ensure heartbeat logger is running
    if not ensure_heartbeat_logger():
        sys.exit(1)

    results = []

    # Launch fresh containers
    for _ in range(args.fresh):
        workspace_id = generate_workspace_id()
        container_name = f"claude-agent-{workspace_id}"

        port = launch_container(workspace_id, container_name)
        if port:
            results.append((container_name, f"fresh workspace: {workspace_id}", port))
        else:
            sys.exit(1)

    # Launch containers with existing workspaces
    for workspace_id in workspace_ids:
        container_name = f"claude-agent-{workspace_id}"

        port = launch_container(workspace_id, container_name)
        if port:
            results.append((container_name, f"existing workspace: {workspace_id}", port))
        else:
            sys.exit(1)

    print("\nContainer details:")
    for container_name, workspace_info, port in results:
        print(f"{container_name} -> {workspace_info} -> {port}")

if __name__ == "__main__":
    main()
