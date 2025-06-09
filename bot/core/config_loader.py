import os
import logging
import json
from dotenv import load_dotenv, set_key, find_dotenv
from typing import Tuple, Optional, Dict, Any

class ConfigManager:
    def __init__(self,
                 config_file_path: str = 'bot_config.json',
                 env_file_path: Optional[str] = None):
        self.logger = logging.getLogger('algo_trader_bot.ConfigManager')

        # Determine .env file path
        if env_file_path:
            self.env_file_path = env_file_path
        else:
            self.env_file_path = find_dotenv(usecwd=True, raise_error_if_not_found=False)
            if not self.env_file_path or not os.path.exists(self.env_file_path):
                project_root_guess = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
                self.env_file_path = os.path.join(project_root_guess, '.env')

        # Ensure .env file exists for dotenv operations, even if empty
        if not os.path.exists(self.env_file_path):
            try:
                with open(self.env_file_path, 'w') as f: # Create empty .env if not exists
                    pass
                self.logger.info(f"Created empty .env file at: {self.env_file_path}")
            except IOError as e:
                self.logger.error(f"Could not create .env file at {self.env_file_path}: {e}")
                # Proceeding without a writable .env file might cause issues for saving API keys.

        self.config_file_path = config_file_path
        self.logger.info(f"ConfigManager initialized. JSON config: '{self.config_file_path}', ENV config: '{self.env_file_path}'")
        self._load_env() # Initial load of .env variables

    def _load_env(self):
        """Loads environment variables from the .env file."""
        # load_dotenv will not override existing system environment variables by default.
        # If override is needed (e.g. .env should always take precedence), set override=True.
        if self.env_file_path and os.path.exists(self.env_file_path):
            load_dotenv(dotenv_path=self.env_file_path, override=True)
            self.logger.debug(f"Environment variables loaded from: {self.env_file_path}")
        else:
            self.logger.debug(f".env file not found at {self.env_file_path}. Using system environment variables or defaults.")


    def load_api_keys(self, use_testnet: bool = False) -> Tuple[Optional[str], Optional[str]]:
        self._load_env() # Ensure latest .env values are loaded
        key_name_prefix = "BINANCE_TESTNET" if use_testnet else "BINANCE_MAINNET"
        api_key = os.getenv(f"{key_name_prefix}_API_KEY")
        api_secret = os.getenv(f"{key_name_prefix}_API_SECRET")

        placeholder_key = f"YOUR_{'TESTNET' if use_testnet else 'MAINNET'}_API_KEY"
        placeholder_secret = f"YOUR_{'TESTNET' if use_testnet else 'MAINNET'}_API_SECRET"

        if api_key == placeholder_key: api_key = None
        if api_secret == placeholder_secret: api_secret = None

        return api_key, api_secret

    def save_api_key_to_env(self, key_name: str, key_value: str) -> bool:
        """Saves a single API key (or secret) to the .env file."""
        try:
            # Create .env if it doesn't exist, as set_key might require it.
            if not os.path.exists(self.env_file_path):
                with open(self.env_file_path, 'w'): pass

            success = set_key(self.env_file_path, key_name, key_value, quote_mode="always")
            if success:
                self.logger.info(f"Saved {key_name} to {self.env_file_path}")
                self._load_env() # Reload env vars after change
            else:
                self.logger.error(f"Failed to save {key_name} to {self.env_file_path} using set_key.")
            return success
        except Exception as e:
            self.logger.error(f"Exception saving {key_name} to .env: {e}", exc_info=True)
            return False

    def load_log_level_from_env(self) -> int: # Renamed to be specific
        self._load_env()
        level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
        return getattr(logging, level_str, logging.INFO)

    def save_app_config(self, config_data: Dict[str, Any]):
        try:
            with open(self.config_file_path, 'w') as f:
                json.dump(config_data, f, indent=4)
            self.logger.info(f"Application config saved to {self.config_file_path}")
        except IOError as e:
            self.logger.error(f"Error saving app config to {self.config_file_path}: {e}", exc_info=True)

    def load_app_config(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.config_file_path):
            self.logger.info(f"App config file {self.config_file_path} not found. Returning None.")
            return None # Or return a default config structure: {'general_settings': {}, 'strategies': {}}
        try:
            with open(self.config_file_path, 'r') as f:
                config_data = json.load(f)
                self.logger.info(f"Application config loaded from {self.config_file_path}")
                return config_data
        except (IOError, json.JSONDecodeError) as e:
            self.logger.error(f"Error loading app config from {self.config_file_path}: {e}", exc_info=True)
            return None


# Standalone functions for initial setup before ConfigManager might be fully available
def load_log_level(env_file_path: Optional[str] = None) -> int:
    """Loads log level from .env, for early logger setup. Uses basic dotenv loading."""
    load_dotenv(dotenv_path=env_file_path if env_file_path and os.path.exists(env_file_path) else find_dotenv(usecwd=True, raise_error_if_not_found=False))
    level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    return getattr(logging, level_str, logging.INFO)

def initial_load_api_keys(use_testnet: bool = False, env_file_path: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Loads API keys from .env, for early setup. Uses basic dotenv loading."""
    load_dotenv(dotenv_path=env_file_path if env_file_path and os.path.exists(env_file_path) else find_dotenv(usecwd=True, raise_error_if_not_found=False))
    key_name_prefix = "BINANCE_TESTNET" if use_testnet else "BINANCE_MAINNET"
    api_key = os.getenv(f"{key_name_prefix}_API_KEY")
    api_secret = os.getenv(f"{key_name_prefix}_API_SECRET")
    placeholder_key = f"YOUR_{'TESTNET' if use_testnet else 'MAINNET'}_API_KEY"
    placeholder_secret = f"YOUR_{'TESTNET' if use_testnet else 'MAINNET'}_API_SECRET"
    if api_key == placeholder_key: api_key = None
    if api_secret == placeholder_secret: api_secret = None
    return api_key, api_secret


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger('test_config_manager')

    # Test with specific paths (assuming .env and bot_config.json are in CWD for this test)
    test_env_path = ".env.test_config_loader"
    test_json_path = "bot_config.test_config_loader.json"

    # Create dummy .env for testing
    with open(test_env_path, "w") as f:
        f.write("BINANCE_TESTNET_API_KEY=test_key_123\n")
        f.write("BINANCE_TESTNET_API_SECRET=test_secret_456\n")
        f.write("LOG_LEVEL=DEBUG\n")

    cm = ConfigManager(config_file_path=test_json_path, env_file_path=test_env_path)

    logger.info("--- Testing ConfigManager ---")
    # Test API Key Loading
    tn_key, tn_secret = cm.load_api_keys(use_testnet=True)
    logger.info(f"Testnet Keys: Key='{tn_key}', Secret Present: {bool(tn_secret)}")
    assert tn_key == "test_key_123"

    # Test Log Level Loading (from env)
    log_lvl = cm.load_log_level_from_env()
    logger.info(f"Log Level from env: {logging.getLevelName(log_lvl)}")
    assert log_lvl == logging.DEBUG

    # Test App Config Save/Load
    test_app_config = {
        "general_settings": {"log_level": "INFO", "some_other_setting": True},
        "strategies": {"strat1": {"type_name": "Pivot", "params": {"p1": 10}}}
    }
    cm.save_app_config(test_app_config)
    loaded_app_config = cm.load_app_config()
    logger.info(f"Loaded App Config: {loaded_app_config}")
    assert loaded_app_config == test_app_config

    # Test saving a specific API key
    cm.save_api_key_to_env("BINANCE_TESTNET_API_KEY", "new_test_key_789")
    new_tn_key, _ = cm.load_api_keys(use_testnet=True)
    logger.info(f"New Testnet Key after save: {new_tn_key}")
    assert new_tn_key == "new_test_key_789"

    # Cleanup test files
    if os.path.exists(test_env_path): os.remove(test_env_path)
    if os.path.exists(test_json_path): os.remove(test_json_path)
    logger.info("--- ConfigManager Test Finished ---")

    # Test standalone functions (used for initial logger setup before CM instance)
    logger.info("--- Testing Standalone Config Functions ---")
    # Create dummy .env in CWD if needed for this part of test
    with open(".env", "w") as f: # Assuming CWD is project root for this test
        f.write("LOG_LEVEL=WARNING\n")
    initial_log_lvl = load_log_level() # Test with default path search
    logger.info(f"Standalone load_log_level: {logging.getLevelName(initial_log_lvl)}")
    assert initial_log_lvl == logging.WARNING
    if os.path.exists(".env"): os.remove(".env") # Clean up CWD .env
```
