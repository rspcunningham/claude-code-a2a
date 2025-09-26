import os

USER_UPLOAD_DIR = "/workspace/user_uploaded_data"
AGENT_OUTPUT_DIR = "/workspace/agent_outputs"


def _list_files(directory: str) -> list[str]:
    """List all files in the given directory"""
    os.makedirs(directory, exist_ok=True)
    return [
        f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))
    ]


def _get_file(directory: str, filename: str, error_context: str) -> bytes:
    """Get content of a specific file from directory"""
    os.makedirs(directory, exist_ok=True)
    file_path = os.path.join(directory, filename)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File {filename} not found in {error_context}")

    with open(file_path, "rb") as f:
        return f.read()


def list_user_files() -> list[str]:
    return _list_files(USER_UPLOAD_DIR)


def save_user_file(filename: str, content: bytes) -> str:
    os.makedirs(USER_UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(USER_UPLOAD_DIR, filename)
    with open(file_path, "wb") as f:
        f.write(content)
    return file_path


def list_agent_outputs() -> list[str]:
    return _list_files(AGENT_OUTPUT_DIR)


def get_agent_output_file(filename: str) -> bytes:
    return _get_file(AGENT_OUTPUT_DIR, filename, "agent outputs")


def get_user_file(filename: str) -> bytes:
    return _get_file(USER_UPLOAD_DIR, filename, "user uploads")
