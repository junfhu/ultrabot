"""ultrabot.config -- configuration subsystem.

Public surface re-exported here for convenience::

    from ultrabot.config import Config, load_config, get_workspace_path
"""

from ultrabot.config.loader import (
    get_config_path,
    load_config,
    save_config,
    set_config_path,
    watch_config,
)
from ultrabot.config.paths import (
    get_cli_history_path,
    get_cron_dir,
    get_data_dir,
    get_logs_dir,
    get_media_dir,
    get_workspace_path,
)
from ultrabot.config.schema import (
    AgentDefaults,
    AgentsConfig,
    Base,
    ChannelsConfig,
    Config,
    ExecToolConfig,
    GatewayConfig,
    HeartbeatConfig,
    MCPServerConfig,
    ProviderConfig,
    ProvidersConfig,
    SecurityConfig,
    ToolsConfig,
    WebSearchConfig,
    WebToolsConfig,
)

__all__ = [
    # Schema models
    "Base",
    "Config",
    "ProviderConfig",
    "ProvidersConfig",
    "AgentDefaults",
    "AgentsConfig",
    "ChannelsConfig",
    "HeartbeatConfig",
    "GatewayConfig",
    "WebSearchConfig",
    "WebToolsConfig",
    "ExecToolConfig",
    "MCPServerConfig",
    "ToolsConfig",
    "SecurityConfig",
    # Loader functions
    "get_config_path",
    "set_config_path",
    "load_config",
    "save_config",
    "watch_config",
    # Path utilities
    "get_workspace_path",
    "get_data_dir",
    "get_logs_dir",
    "get_media_dir",
    "get_cron_dir",
    "get_cli_history_path",
]
