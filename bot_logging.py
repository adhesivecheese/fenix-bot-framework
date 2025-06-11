#!/usr/bin/env python3

from loguru import logger #Must be first import
from sys import stdout

from .bot_config import load_config, get_log_path

config = load_config()
LOG_NAME = config["LOGGING"].get("Log_Name", "bot")
LOG_ROTATION_DAYS = config["LOGGING"].getint("Rotation_Days", 1)
LOG_RETENTION_DAYS = config["LOGGING"].getint("Retention_Days", 30)
DEBUG_LOGS = config["LOGGING"].getboolean("Debug_Logs", False)


log_dir = get_log_path()
log_dir.mkdir(parents=True, exist_ok=True)

# Remove the default logger
logger.remove() 

# Set custom log levels
ephemeral_level     = logger.level("EPHEMERAL", no=11)
submissions_level   = logger.level("SUBMISSIONS", no=20)
comments_level      = logger.level("COMMENTS", no=20)
hot_level           = logger.level("HOT", no=20)
rising_level        = logger.level("RISING", no=20)
top_level           = logger.level("TOP", no=20)
controversial_level = logger.level("CONTROVERSIAL", no=20)
unmoderated_level   = logger.level("UNMODEREATED", no=20)
spam_level          = logger.level("SPAM", no=20)
removed_level       = logger.level("REMOVED", no=20)
modqueue_level      = logger.level("MODQUEUE", no=20)
edited_level        = logger.level("EDITED", no=20)
modlog_level        = logger.level("MODLOG", no=20)
mm_convo_level      = logger.level("MODMAIL", no=20)
reports_level       = logger.level("REPORTS", no=20)

approve_level       = logger.level("APPROVE", no=22, color="<green>")
remove_level        = logger.level("REMOVE", no=22, color="<yellow>")
ban_level           = logger.level("BAN", no=24, color="<red>")

# Set Log formats for console and text file log
log_format = "{time: YYYY-MM-DD HH:mm:ss:SSZZ} | {level: <14} | "
log_format += "{name}:{function}:{line} | {message}"
console_format = "{time: YYYY-MM-DD HH:mm:ss:SSZZ} | {level: <14} | {message}"

# if DEBUG_LOGS is set, include extra information in the text log.
if DEBUG_LOGS == True:
	log_level = "DEBUG"
	console_log_level = "DEBUG"
else:
	log_format = console_format
	log_level = "INFO"
	console_log_level = "EPHEMERAL"

 
# Add the text log.
logger.add(
	log_dir / "bot_{time}.log"
	, rotation=f"{LOG_ROTATION_DAYS} days"
	, retention=f"{LOG_RETENTION_DAYS} days"
	, compression="zip"
	, enqueue=True
	, level=log_level
	, format=log_format
	, backtrace=DEBUG_LOGS
	, diagnose=DEBUG_LOGS
)

# Add the Console log.
logger.add(
	stdout
	, format=console_format
	, colorize=True
	, level=console_log_level
)
