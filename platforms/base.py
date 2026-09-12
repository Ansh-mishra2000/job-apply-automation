"""
Base class for job application platform automation.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from database import JobDatabase
from utils.logger import logger


class BasePlatform(ABC):
    def __init__(self, name: str, config: Dict[str, Any], db: JobDatabase, headless: bool = False):
        self.name = name.lower()
        self.config = config
        self.db = db
        self.headless = headless
        self.limit_reached = self.db.is_daily_limit_reached(self.name)

    @abstractmethod
    def login(self):
        """Interactive headed login to establish and persist session."""
        pass

    @abstractmethod
    def check_auth(self) -> bool:
        """Verifies whether the current persistent session is authenticated."""
        pass

    @abstractmethod
    def run(
        self,
        keyword_override: Optional[str] = None,
        location_override: Optional[str] = None,
        time_filter_override: Optional[str] = None,
    ) -> int:
        """
        Executes job search and application workflow for this platform until
        the daily quota/limit is reached or exceeded.
        Returns the number of jobs successfully applied in this run.
        """
        pass

    @abstractmethod
    def list_jobs(
        self,
        keyword: str,
        location: str,
        time_filter: str = "24h",
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Searches and returns job listings matching position, location, and time window
        (24h, 7d, 15d, 30d) without necessarily applying.
        """
        pass

    @abstractmethod
    def update_resume(self) -> bool:
        """
        Uploads/refreshes the latest resume PDF on the platform to update
        the profile timestamp and boost recruiter search ranking.
        """
        pass
