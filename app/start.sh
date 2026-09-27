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

# Start the API
echo "🎉 Starting FastAPI server..."
echo "📖 API docs will be available at: http://localhost:8000/docs"
cd api && uvicorn main:app --reload --host 0.0.0.0 --port 8000