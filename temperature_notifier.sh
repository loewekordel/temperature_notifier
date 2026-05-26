#!/bin/bash
cd /home/jarvis/scripts/temperature_notifier
/home/jarvis/.local/bin/uv run python main.py "$@"
