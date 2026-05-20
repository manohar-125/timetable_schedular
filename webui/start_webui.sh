#!/bin/bash

# Timetable Scheduler Web UI Startup Script

echo "========================================="
echo "  Timetable Scheduler Web UI"
echo "========================================="

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found!"
    echo "Please create it first with: python3 -m venv venv"
    exit 1
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Start the FastAPI server
echo ""
echo "========================================="
echo "✅ Starting Timetable Scheduler Server..."
echo "========================================="
echo ""
echo "🌐 Open your browser and go to:"
echo "   http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop the server"
echo "========================================="
echo ""

cd webui
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
