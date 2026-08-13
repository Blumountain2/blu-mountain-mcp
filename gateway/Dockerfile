# MCP Gateway Dockerfile
# Multi-stage build for optimized production image

# ====================================
# Build Stage
# ====================================
FROM python:3.11-slim as builder

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ====================================
# Production Stage  
# ====================================
FROM python:3.11-slim as production

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r mcpgateway && useradd -r -g mcpgateway mcpgateway

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=mcpgateway:mcpgateway . /app/

# Create necessary directories
RUN mkdir -p /app/logs /app/config && \
    chown -R mcpgateway:mcpgateway /app

# Switch to non-root user
USER mcpgateway

# Expose port
EXPOSE 8888

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8888/health || exit 1

# Default environment variables
# HOME must be writable by mcpgateway: FastMCP's OAuth Proxy resolves its
# encrypted-token storage directory under the process's home directory, and
# the non-root user created above has none by default (no -m on useradd).
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8888 \
    LOG_LEVEL=info \
    HOME=/app

# Start the application
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8888"]