import yaml
import os
from typing import Dict, Any, Optional

CONFIG_FILE = 'config.yaml'
_CACHED_CONFIG = None

def load_config() -> Optional[Dict[str, Any]]:
    """
    Load configuration from config.yaml with caching.

    Returns
    -------
    Optional[Dict[str, Any]]
        Configuration dictionary or None if file not found.
    """
    global _CACHED_CONFIG
    
    if _CACHED_CONFIG is not None:
        return _CACHED_CONFIG

    if not os.path.exists(CONFIG_FILE):
        return None
        
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            _CACHED_CONFIG = yaml.safe_load(f)
            return _CACHED_CONFIG
    except Exception as e:
        print(f"Error loading config: {e}")
        return None

# Load once at module level mostly for static access patterns if needed,
# but using getters is preferred.
CFG = load_config()

# Helper accessors
def get_system_config() -> Dict[str, Any]:
    """
    Get system configuration.

    Returns
    -------
    Dict[str, Any]
        System config dict.
    """
    cfg = load_config()
    return cfg.get('system', {}) if cfg else {}

def get_gatekeeper_config() -> Dict[str, Any]:
    """
    Get gatekeeper configuration.

    Returns
    -------
    Dict[str, Any]
        Gatekeeper config dict.
    """
    cfg = load_config()
    return cfg.get('gatekeeper', {}) if cfg else {}

def get_scoring_config() -> Dict[str, Any]:
    """
    Get scoring configuration.

    Returns
    -------
    Dict[str, Any]
        Scoring config dict.
    """
    cfg = load_config()
    return cfg.get('scoring', {}) if cfg else {}
