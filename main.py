# =============================================================================
# main.py
# Entry point for the Water Leak and Usage Monitoring System.
# Imports all modules and starts the MicroDot web server.
# =============================================================================

from server import start_server

# Start the web server (blocking call — runs indefinitely)
start_server()
