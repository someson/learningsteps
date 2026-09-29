#!/bin/bash

# LearningSteps API Startup Script
echo "🚀 Starting LearningSteps API..."

# Check if we're in the right directory
if [ ! -f "api/main.py" ]; then
    echo "❌ Please run this script from the app/ directory"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r api/requirements.txt

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found. Make sure to set DATABASE_URL"
fi

# Build the web UI (served at /) if Node is available
if command -v npm >/dev/null 2>&1; then
    echo "🎨 Building web UI..."
    (cd frontend && npm ci && npm run build)
else
    echo "⚠️  Warning: npm not found, the web UI at / will not be available"
fi

# Start the API
echo "🎉 Starting FastAPI server..."
echo "🖥️  Web UI will be available at: http://localhost:8000/"
echo "📖 API docs will be available at: http://localhost:8000/docs"
cd api && uvicorn main:app --reload --host 0.0.0.0 --port 8000