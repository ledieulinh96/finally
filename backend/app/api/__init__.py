"""HTTP API: REST routes and static frontend serving."""

from .routes import create_api_router
from .static import mount_static

__all__ = ["create_api_router", "mount_static"]
