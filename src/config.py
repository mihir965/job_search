"""Configuration loading and validation."""
import os
import re
import logging
from pathlib import Path
from typing import Any, Dict
import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env file if it exists
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logger.debug(f"Loaded environment variables from {env_path}")
else:
    logger.debug("No .env file found, using system environment variables")


class Config:
    """Singleton configuration object loaded from YAML."""

    _instance = None

    def __new__(cls, config_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
            cls._instance._data = {}  # Initialize empty data
        return cls._instance

    def __init__(self, config_path: str = None):
        if self._loaded:
            return

        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            # Don't raise error on init - allow lazy loading
            logger.warning(f"Config file not found: {config_path}")
            return

        with open(config_path) as f:
            raw_config = yaml.safe_load(f)

        # Resolve environment variables in config values
        self._data = self._resolve_env_vars(raw_config)
        self._loaded = True
        logger.info(f"Loaded configuration from {config_path}")

    def _resolve_env_vars(self, obj: Any) -> Any:
        """Recursively resolve ${ENV_VAR} references in config."""
        if isinstance(obj, dict):
            return {k: self._resolve_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            # Match ${VAR_NAME} pattern
            pattern = r'\$\{([^}]+)\}'
            matches = re.findall(pattern, obj)
            result = obj
            for var_name in matches:
                env_value = os.getenv(var_name, "")
                result = result.replace(f"${{{var_name}}}", env_value)
            return result
        else:
            return obj

    def get(self, key_path: str, default=None):
        """Get config value by dot-separated path (e.g., 'smtp.server')."""
        keys = key_path.split('.')
        value = self._data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    @property
    def profile(self) -> Dict:
        return self._data.get('profile', {})

    @property
    def smtp(self) -> Dict:
        return self._data.get('smtp', {})

    @property
    def apis(self) -> Dict:
        return self._data.get('apis', {})

    @property
    def monitor(self) -> Dict:
        return self._data.get('monitor', {})

    @property
    def outreach(self) -> Dict:
        return self._data.get('outreach', {})

    @property
    def llm(self) -> Dict:
        return self._data.get('llm', {})

    def validate(self) -> bool:
        """Check that required fields are present and valid."""
        required = [
            'profile.name',
            'profile.email',
            'smtp.server',
            'smtp.port',
        ]

        missing = []
        for path in required:
            if not self.get(path):
                missing.append(path)

        if missing:
            logger.error(f"Missing required config fields: {', '.join(missing)}")
            return False

        # Warn about missing optional API keys
        if not self.get('apis.hunter_key'):
            logger.warning("Hunter.io API key not set - contact enrichment will be limited")
        if not self.get('apis.apollo_key'):
            logger.warning("Apollo.io API key not set - contact enrichment will be limited")
        if not self.get('apis.anthropic_key') and self.get('llm.enabled', True):
            logger.warning("Anthropic API key not set - LLM email personalization disabled")

        if not self.get('smtp.user') or not self.get('smtp.password'):
            logger.warning("SMTP credentials not set - email sending will not work")

        return True


# Global singleton instance
config = Config()
