import logging
import sys

def get_logger(name: str) -> logging.Logger:
    """Configures and returns a contextual logger for Veyra."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if setup multiple times
    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            fmt="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S %z"
        )
        
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # Configure discord.py logger to output to our handler, but only do this once
        if name == "VEYRA":
            discord_logger = logging.getLogger("discord")
            discord_logger.setLevel(logging.WARNING)
            if not discord_logger.handlers:
                discord_logger.addHandler(console_handler)
            
    return logger

log = get_logger("VEYRA")
