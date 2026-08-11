from enum import Enum
import time

class HealthState(Enum):
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    FAILED = "FAILED"

class HealthSystem:
    """Tracks the health and readiness of the Veyra application."""
    def __init__(self):
        self.state = HealthState.STARTING
        self.start_time = time.time()
        self.db_connected = False
        self.services_initialized = False
        self.discord_ready = False

    @property
    def uptime(self) -> int:
        """Returns uptime in seconds."""
        return int(time.time() - self.start_time)

health_system = HealthSystem()
