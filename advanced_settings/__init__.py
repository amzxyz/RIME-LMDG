from .deployment import deploy_rime_platform, detect_linux_im_system

from .core import (
    ConflictSeverity,
    KeyClaim,
    KeyConflict,
    KeySpec,
    LiveKeyRegistry,
    LoadedRimeDocument,
    RimeKeyConflictEngine,
    RimeYamlEngine,
    RimeYamlError,
    SaveTransaction,
    YamlDuplicateIssue,
    is_managed_config_yaml,
    is_managed_source_yaml,
    is_rime_dictionary,
)

try:
    from .mixin import AdvancedSettingsMixin
except ModuleNotFoundError as error:
    if error.name != "PySide6":
        raise
    AdvancedSettingsMixin = None

__all__ = [
    "AdvancedSettingsMixin",
    "ConflictSeverity",
    "KeyClaim",
    "KeyConflict",
    "KeySpec",
    "LiveKeyRegistry",
    "LoadedRimeDocument",
    "RimeKeyConflictEngine",
    "RimeYamlEngine",
    "RimeYamlError",
    "SaveTransaction",
    "YamlDuplicateIssue",
    "is_managed_config_yaml",
    "is_managed_source_yaml",
    "is_rime_dictionary",
    "deploy_rime_platform",
    "detect_linux_im_system",
]
