"""
In-process daily scheduler for job application engine.
"""

from datetime import datetime
import time
from typing import Any, Callable, Dict
import schedule
from rich.panel import Panel
from rich.table import Table

from utils.logger import console, logger


def run_scheduler(job_fn: Callable[[], None], cron_time: str = "09:30"):
    """Schedules job_fn to run every day at cron_time."""
    logger.info(f"Setting daily schedule for [bold green]{cron_time}[/bold green]...")

    schedule.every().day.at(cron_time).do(job_fn)

    next_run = schedule.next_run()
    console.print(
        Panel(
            f"[bold]Daily Job Scheduler Active[/bold]\n"
            f"• Scheduled Time: [green]{cron_time}[/green] daily\n"
            f"• Next Scheduled Run: [yellow]{next_run.strftime('%Y-%m-%d %H:%M:%S') if next_run else 'Pending'}[/yellow]\n"
            f"• Press [red]Ctrl+C[/red] to exit scheduler at any time.",
            title="Job Apply Daemon",
            border_style="cyan",
        )
    )

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")
