#!/bin/bash

# Navigate to the script directory
cd /home/jarvis/scripts/temperature_notifier

# Activate the virtual environment
source venv/bin/activate

# Run the Python script
python main.py "$@"
