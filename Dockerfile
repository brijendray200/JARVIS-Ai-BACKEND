# ==========================================
# Production Dockerfile for FastAPI Backend
# Python Version: 3.10-slim
# ==========================================

FROM python:3.10-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Set working directory
WORKDIR /app

# Install system dependencies (ffmpeg is required for whisper/tts audio processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt first to take advantage of Docker layer caching
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create and switch to a non-root user for security best practices
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Expose default port (Render will override this dynamically via $PORT)
EXPOSE 8000

# Startup command: Uses 'sh -c' to dynamically expand $PORT assigned by cloud providers (Render)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
