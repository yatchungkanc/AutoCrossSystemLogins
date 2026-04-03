#!/usr/bin/env python3
"""Root-level entry point for the dashboard agent.

Usage:
    python run.py                          # Launch browser with all dashboards
    python run.py cloudhealth              # Generate CloudHealth report
    python run.py cloudhealth "cost by service, anomaly detection"
"""
import asyncio
import sys
from pathlib import Path

# Ensure dashboard-agent/ is on the path so `src.*` imports resolve correctly
sys.path.insert(0, str(Path(__file__).resolve().parent / "dashboard-agent"))

if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "cloudhealth":
        from src.cloudhealth_report import main as cloudhealth_main
        focus_area = args[1] if len(args) > 1 else ""
        asyncio.run(cloudhealth_main(focus_area))
    else:
        from src.orchestrator import main
        main()
