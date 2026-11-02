"""Central application and persistence compatibility versions."""

__version__ = "0.2.0"

# Increment only when a persisted schema requires migration.
STORE_SCHEMA_VERSION = 2
MODEL_REGISTRY_SCHEMA_VERSION = 2
SKILL_REGISTRY_SCHEMA_VERSION = 1
EVOLUTION_SCHEMA_VERSION = 1

# Local intelligence package manifests supported by this release.
LOCAL_PACKAGE_MANIFEST_VERSION = 1
MIN_COMPATIBLE_APP_VERSION = "0.2.0"
