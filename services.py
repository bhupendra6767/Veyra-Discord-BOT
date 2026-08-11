from typing import Dict, Any
from errors import ServiceError

class ServiceRegistry:
    """Lightweight service registry for Veyra Core Engine."""
    def __init__(self):
        self._services: Dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        """Registers a service by name."""
        if name in self._services:
            raise ServiceError(f"Service '{name}' is already registered.")
        self._services[name] = service

    def get(self, name: str) -> Any:
        """Retrieves a service by name."""
        if name not in self._services:
            raise ServiceError(f"Service '{name}' is not registered.")
        return self._services[name]

registry = ServiceRegistry()
