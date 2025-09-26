# Base stage - common dependencies
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies including Node.js
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Copy requirements
COPY pyproject.toml uv.lock ./

# Install uv for fast dependency management
RUN pip install uv

# Install dependencies
RUN uv sync --frozen

# Copy application code
COPY . .

# Create workspace directory and initialize
RUN mkdir -p /workspace
WORKDIR /workspace
RUN git init
COPY container_files/pyproject.toml .
COPY container_files/CLAUDE.md .
RUN mkdir -p user_uploaded_data
RUN mkdir -p agent_outputs
RUN mkdir -p scripts
RUN uv venv

# finish setup of container
WORKDIR /app
EXPOSE 9999

# Run the server
CMD ["uv", "run", "a2a_server.py"]
