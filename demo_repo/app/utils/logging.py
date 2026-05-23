import datetime

def log_info(message: str) -> None:
    """Log an info level message with a timestamp."""
    timestamp = datetime.datetime.now().isoformat()
    print(f"[{timestamp}] INFO: {message}")

def log_error(message: str) -> None:
    """Log an error level message with a timestamp."""
    timestamp = datetime.datetime.now().isoformat()
    print(f"[{timestamp}] ERROR: {message}")
