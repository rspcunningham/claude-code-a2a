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

# Create workspace directory
RUN mkdir -p /workspace

# Expose
EXPOSE 9999

# Run the server
CMD ["uv", "run", "python", "a2a_server.py"]
