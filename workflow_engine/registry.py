import logging
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger(__name__)

class RegistryError(Exception):
    pass

class JobRegistry:
    def __init__(self):
        self._handlers: Dict[str, Callable] = {}

    def register(self, job_type: str):
        """Decorator to register a function as the handler for a given job_type."""
        def decorator(func: Callable):
            if job_type in self._handlers:
                logger.warning("Overwriting existing job handler for %s", job_type)
            self._handlers[job_type] = func
            return func
        return decorator

    def register_func(self, job_type: str, func: Callable):
        """Programmatic registration of a handler."""
        self._handlers[job_type] = func

    def get_handler(self, job_type: str) -> Optional[Callable]:
        return self._handlers.get(job_type)

    def is_registered(self, job_type: str) -> bool:
        return job_type in self._handlers

    def list_registered(self) -> list[str]:
        return sorted(list(self._handlers.keys()))


# Global default registry instance
registry = JobRegistry()
