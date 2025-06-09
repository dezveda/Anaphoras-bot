import os
import logging
from dotenv import load_dotenv

def _load_env(env_file_path: str = None):
    """Helper function to load .env file."""
    if env_file_path:
        load_dotenv(dotenv_path=env_file_path)
    else:
        # load_dotenv will search for .env in the current directory and parent directories.
        # For a typical project structure where .env is in the root:
        # If this script is in bot/core/, path to root .env is ../../.env
        # Providing a default search path can be helpful.
        default_path = os.path.join(os.path.dirname(__file__), '../../.env')
        if os.path.exists(default_path):
            load_dotenv(dotenv_path=default_path)
        else:
            load_dotenv() # Standard search if default_path not found


def load_api_keys(env_file_path: str = None) -> tuple[str | None, str | None]:
    """
    Loads Binance API key and secret from a .env file.

    Args:
        env_file_path (str, optional): Path to the .env file.
                                       If None, uses a default path or standard dotenv search.
    Returns:
        tuple[str | None, str | None]: (api_key, api_secret)
    """
    _load_env(env_file_path)

    api_key = os.getenv("BINANCE_TESTNET_API_KEY")
    api_secret = os.getenv("BINANCE_TESTNET_API_SECRET")

    # Example for switching to Mainnet if needed (e.g., based on another env var)
    # if os.getenv("USE_MAINNET_KEYS") == "true":
    #     api_key = os.getenv("BINANCE_MAINNET_API_KEY")
    #     api_secret = os.getenv("BINANCE_MAINNET_API_SECRET")

    return api_key, api_secret

def load_log_level(env_file_path: str = None) -> int:
    """
    Loads the logging level from a .env file.

    Args:
        env_file_path (str, optional): Path to the .env file.
                                       If None, uses a default path or standard dotenv search.
    Returns:
        int: The logging level (e.g., logging.INFO, logging.DEBUG). Defaults to logging.INFO.
    """
    _load_env(env_file_path)

    level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    level_mapping = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    return level_mapping.get(level_str, logging.INFO)


if __name__ == '__main__':
    # This example assumes .env might be in the project root (../../.env)
    # Create a dummy .env at that location for testing this script directly.
    # Example:
    # .env file content:
    # BINANCE_TESTNET_API_KEY="your_test_key"
    # BINANCE_TESTNET_API_SECRET="your_test_secret"
    # LOG_LEVEL="DEBUG"

    print("--- Testing config_loader.py ---")

    # Test load_api_keys
    key, secret = load_api_keys() # Will use _load_env's default logic
    print(f"Loaded API Keys: Key set: {bool(key)}, Secret set: {bool(secret)}")
    if not key or not secret:
        print("  Note: API keys not found. Ensure .env is in the project root with BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET.")

    # Test load_log_level
    log_level_int = load_log_level()
    log_level_name = logging.getLevelName(log_level_int)
    print(f"Loaded Log Level: {log_level_name} (Value: {log_level_int})")
    if log_level_name == 'INFO' and os.getenv('LOG_LEVEL') is None:
        print("  Note: LOG_LEVEL not found in .env, defaulted to INFO.")
    elif os.getenv('LOG_LEVEL'):
        print(f"  LOG_LEVEL found in .env: {os.getenv('LOG_LEVEL')}")
    else:
        print("  LOG_LEVEL not found, and it defaulted to INFO.")

    # Example of using these with other modules (conceptual)
    # from ..connectors.binance_connector import BinanceAPI
    # from .logger_setup import setup_logger

    # if key and secret:
    #     current_log_level = load_log_level()
    #     logger = setup_logger(level=current_log_level)
    #     logger.info("Logger configured with level from .env")

    #     connector = BinanceAPI(api_key=key, api_secret=secret, testnet=True)
    #     try:
    #         logger.debug(f"Pinging Binance with loaded keys...")
    #         ping_result = connector.ping()
    #         logger.info(f"Ping successful: {ping_result}")
    #     except Exception as e:
    #         logger.error(f"Error pinging Binance: {e}")
    # else:
    #     print("Cannot fully test without API keys in .env")
    print("--- End of config_loader.py test ---")

```
