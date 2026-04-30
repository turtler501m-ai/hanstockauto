import sys
from loguru import logger
from src.config import config
import os

# Remove default handler
logger.remove()

# Add console handler when the process has an attached stream.
console_sink = sys.stdout or sys.stderr
if console_sink is not None:
    logger.add(
        console_sink,
        format="<green>{time:YYYY-MM-DD HH:mm:ss KST}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )

# Add file handler with rotation
log_dir = os.path.dirname(config.log_file)
if log_dir:
    os.makedirs(log_dir, exist_ok=True)

logger.add(
    config.log_file,
    format="{time:YYYY-MM-DD HH:mm:ss KST} | {level: <8} | {name}:{function}:{line} - {message}",
    level="INFO",
    rotation="10 MB",
    retention="30 days",
    encoding="utf-8"
)
