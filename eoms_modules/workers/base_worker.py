from abc import ABC, abstractmethod
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class BaseWorker(ABC):
    """
    Base class for all Automation Center workers.

    Every Automation Center worker should inherit from this class.
    """

    def __init__(self, name: str):
        self._name = name
        self._status = "OFFLINE"
        self._started_at = None
        self._last_run = None
        self._last_error = None

    def name(self):
        return self._name

    def status(self):
        return self._status

    def start(self):
        self._status = "ONLINE"
        self._started_at = utc_now()

    def stop(self):
        self._status = "OFFLINE"

    def set_last_run(self):
        self._last_run = utc_now()

    def set_error(self, error):
        self._last_error = str(error)
        self._status = "ERROR"

    def clear_error(self):
        self._last_error = None

    def health(self):
        return {
            "name": self._name,
            "status": self._status,
            "started_at": self._started_at,
            "last_run": self._last_run,
            "last_error": self._last_error,
        }

    @abstractmethod
    def run(self):
        """
        Execute the worker's primary task.
        Must be implemented by each worker.
        """
        pass