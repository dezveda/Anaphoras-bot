import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger(name: str = 'algo_trader_bot',
                   log_file: str = 'bot_activity.log',
                   level: int = None,
                   log_directory: str = 'logs') -> logging.Logger:
    """
    Sets up a logger with file and console handlers.

    Args:
        name (str): Name of the logger.
        log_file (str): Name of the log file.
        level (int, optional): Logging level. If None, tries to load from LOG_LEVEL env var or defaults to INFO.
        log_directory (str): Directory to store log files. Defaults to 'logs'.

    Returns:
        logging.Logger: Configured logger instance.
    """
    if level is None:
        env_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
        level = getattr(logging, env_level_str, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent adding multiple handlers if logger already configured (e.g., in Jupyter)
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create log directory if it doesn't exist
    if not os.path.exists(log_directory):
        try:
            os.makedirs(log_directory)
        except OSError as e:
            # Handle case where directory creation fails (e.g. permission issues)
            # For now, print an error and continue without file logging if it fails
            print(f"Error creating log directory {log_directory}: {e}. File logging may be disabled.")
            log_file_path = log_file # Try to log in current directory
    else:
        log_file_path = os.path.join(log_directory, log_file)


    # File Handler - Rotates log file if it reaches a certain size
    try:
        fh = RotatingFileHandler(log_file_path, maxBytes=10*1024*1024, backupCount=5, mode='a', encoding='utf-8') # 10MB per file, 5 backups
        fh.setLevel(level)
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(funcName)s - %(message)s')
        fh.setFormatter(file_formatter)
        logger.addHandler(fh)
    except Exception as e:
        print(f"Error setting up file handler for logging at {log_file_path}: {e}")


    # Console Handler
    ch = logging.StreamHandler()
    ch.setLevel(level) # Console can have its own level, e.g. logging.WARNING in production
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    ch.setFormatter(console_formatter)
    logger.addHandler(ch)

    # Initial log message to confirm setup
    # logger.info(f"Logger '{name}' configured with level {logging.getLevelName(level)}. Logging to {log_file_path} and console.")

    return logger

if __name__ == '__main__':
    # Example usage:
    # First, ensure .env can be loaded if LOG_LEVEL is to be tested from there
    from dotenv import load_dotenv
    # Assuming .env is in project root, and this script is in bot/core/
    dotenv_path = os.path.join(os.path.dirname(__file__), '../../.env')
    load_dotenv(dotenv_path=dotenv_path) # Load .env to make LOG_LEVEL available

    # Test with default name and file, level from env or INFO
    default_logger = setup_logger()
    default_logger.debug("This is a debug message (default logger).")
    default_logger.info("This is an info message (default logger).")
    default_logger.warning("This is a warning message (default logger).")
    default_logger.error("This is an error message (default logger).")

    print(f"Default logger handlers: {default_logger.handlers}")


    # Test with specific name, file, and level
    custom_logger = setup_logger(name='MyCustomBot', log_file='custom_bot.log', level=logging.DEBUG, log_directory='custom_logs')
    custom_logger.debug("This is a debug message (custom_logger).")
    custom_logger.info("This is an info message (custom_logger).")

    another_logger_instance = logging.getLogger('algo_trader_bot') # Get the first logger instance
    another_logger_instance.info("Testing if the first logger instance is still working.")

    # Test what happens if called again (should not duplicate handlers)
    # default_logger_again = setup_logger()
    # default_logger_again.info("Testing handler duplication for default_logger.")
    # print(f"Default logger (again) handlers: {default_logger_again.handlers}")


    # Verify log files are created in 'logs' and 'custom_logs' directories respectively.
    # Check their content.
```
