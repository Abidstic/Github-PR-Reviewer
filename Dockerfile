# Multi-stage build for optimized image size
FROM python:3.10-slim as builder
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies in ORDER
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir python-dotenv pyyaml PyGithub requests && \
    pip install --no-cache-dir langchain==0.3.0 langchain-openai==0.2.0 \
    langchain-community==0.3.0 langchain-core==0.3.0 openai==1.56.1 && \
    pip install --no-cache-dir torch==2.2.0 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir sentence-transformers==2.5.1 faiss-cpu==1.7.4 && \
    pip install --no-cache-dir pandas==2.1.4 numpy==1.24.3 flask==3.0.0 \
    gunicorn==21.2.0 pydantic==2.7.4

# Production stage
FROM python:3.10-slim
WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create necessary directories with proper permissions
RUN mkdir -p data/cache data/profiles/reviewers data/profiles/developers data/raw/reviewers logs && \
    chmod -R 755 data logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose port (Railway uses $PORT)
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
CMD curl -f http://localhost:${PORT:-5000}/health || exit 1

# Run application
CMD python app.py --mode webhook