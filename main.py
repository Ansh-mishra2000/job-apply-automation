"""
Main CLI entrypoint for LinkedIn and Naukri automated job application engine.
Includes support for targeted multi-position searches, time-window filtering (24h, 7d, 15d, 30d),
viewing live listings, and automated applying.
"""

import argparse
from datetime import date
from pathlib import Path
import subprocess
import sys
from typing import Any, List, Optional
from rich.panel import Panel
from rich.table import Table

from config_loader import load_config, get_resume_path
from database import JobDatabase
from platforms.linkedin import LinkedInPlatform
from platforms.naukri import NaukriPlatform
from platforms.workday_portal import WorkdayPortalScanner
from scheduler import run_scheduler
from utils.ats_filler import ExternalATSHandler
from utils.browser import BrowserManager
from utils.logger import console, logger


def normalize_positions(pos_arg: Any, config: dict) -> List[str]:
    """Normalizes position argument into a clean list of job titles."""
    if not pos_arg:
        return config.get("search", {}).get("keywords", ["DevOps Engineer"])

    positions = []
    items = pos_arg if isinstance(pos_arg, list) else [pos_arg]
    for item in items:
        for p in str(item).split(","):
            p_clean = p.strip()
            if p_clean and p_clean not in positions:
                positions.append(p_clean)
    return positions if positions else config.get("search", {}).get("keywords", ["DevOps Engineer"])


def normalize_locations(loc_arg: Any, config: dict) -> List[str]:
    """Normalizes location argument into a clean list of locations."""
    if not loc_arg:
        return config.get("search", {}).get("locations", ["India"])

    locations = []
    items = loc_arg if isinstance(loc_arg, list) else [loc_arg]
    for item in items:
        for l in str(item).split(","):
            l_clean = l.strip()
            if l_clean and l_clean not in locations:
                locations.append(l_clean)
    return locations if locations else config.get("search", {}).get("locations", ["India"])


def normalize_time_filters(time_arg: Any, config: dict) -> List[str]:
    """Normalizes time filter argument into an ordered list of search windows (left to right)."""
    if time_arg:
        if isinstance(time_arg, list):
            items = []
            for t in time_arg:
                for sub in str(t).split(","):
                    c = sub.strip()
                    if c and c not in items:
                        items.append(c)
            return items if items else ["24h"]
        return [t.strip() for t in str(time_arg).split(",") if t.strip()]

    cfg_val = config.get("search", {}).get("date_posted", ["24h", "7d"])
    if isinstance(cfg_val, list):
        return [str(t).strip() for t in cfg_val if str(t).strip()]
    if isinstance(cfg_val, str) and "," in cfg_val:
        return [t.strip() for t in cfg_val.split(",") if t.strip()]
    return [str(cfg_val).strip()] if str(cfg_val).strip() else ["24h"]


def determine_headless_mode(args, config) -> bool:
    """Determines whether to run in background (headless) or visible mode."""
    if getattr(args, "headless", False):
        return True
    if getattr(args, "visible", False):
        return False

    display_mode = config.get("execution", {}).get("display_mode", "prompt")
    if display_mode == "background":
        return True
    if display_mode == "visible":
        return False

    if sys.stdin.isatty():
        console.print("\n[bold cyan]Browser Display Preference:[/bold cyan]")
        console.print("  [1] [bold green]Visible Window[/bold green] (watch the browser apply in real-time)")
        console.print("  [2] [bold yellow]Background[/bold yellow] (headless mode, silent and low resource)")
        choice = input("Select mode [1/2] (default: 1): ").strip()
        return choice == "2"

    return True


def execute_job_apply(
    platform_name: str = "all",
    headless: bool = False,
    position: Optional[Any] = None,
    location: Optional[Any] = None,
    time_filter: Optional[Any] = None,
):
    """Executes the job application loop across enabled platforms, target positions, and cascading time windows."""
    config = load_config()
    db = JobDatabase()

    search_keywords = normalize_positions(position, config)
    search_locations = normalize_locations(location, config)
    today_str = date.today().strftime("%Y-%m-%d")
    time_windows = normalize_time_filters(time_filter, config)
    time_windows_display = " -> ".join(time_windows)

    console.print(
        Panel(
            f"[bold]Starting Automated Job Application Engine[/bold]\n"
            f"• Date: [cyan]{today_str}[/cyan]\n"
            f"• Target Position(s): [bold green]{', '.join(search_keywords)}[/bold green]\n"
            f"• Location(s): [cyan]{', '.join(search_locations)}[/cyan]\n"
            f"• Cascading Search Windows: [yellow]{time_windows_display}[/yellow] (Left-to-Right Priority)\n"
            f"• Mode: [{'yellow]Background (Headless)' if headless else 'green]Visible Window'}[/]\n"
            f"• Target Platform(s): [magenta]{platform_name.upper()}[/magenta]",
            title="Auto Apply Bot",
            border_style="cyan",
        )
    )

    resume = get_resume_path(config)
    if not resume:
        logger.warning(
            f"Resume file '{config.get('profile', {}).get('resume_path')}' not found. "
            "Applications requiring resume upload will fall back to profile default."
        )
    else:
        logger.info(f"Using resume: [bold green]{resume.name}[/bold green]")

    # Auto-refresh profile resume before applying to bump recruiter ranking
    auto_refresh = config.get("profile_refresh", {}).get("auto_update_before_apply", True)
    if auto_refresh and resume:
        logger.step("--- Bumping profile with latest resume to refresh recruiter visibility ---")
        if platform_name in ("all", "naukri") and config.get("platforms", {}).get("naukri", {}).get("enabled", True):
            np = NaukriPlatform(config, db, headless=headless)
            np.update_resume()
        if platform_name in ("all", "linkedin") and config.get("platforms", {}).get("linkedin", {}).get("enabled", True):
            lp = LinkedInPlatform(config, db, headless=headless)
            lp.update_resume()

    # Initialize active platforms and verify daily quotas
    active_platforms: List[str] = []

    linkedin_cfg = config.get("platforms", {}).get("linkedin", {})
    linkedin_enabled = linkedin_cfg.get("enabled", True) and platform_name in ("all", "linkedin")
    linkedin_max = linkedin_cfg.get("max_daily_applications", 50)
    linkedin_today = db.get_daily_applied_count("linkedin")
    if linkedin_enabled:
        if db.is_daily_limit_reached("linkedin") or linkedin_today >= linkedin_max:
            logger.info(f"LinkedIn daily quota already reached for today ({linkedin_today}/{linkedin_max}). Skipping LinkedIn.")
        else:
            active_platforms.append("linkedin")

    naukri_cfg = config.get("platforms", {}).get("naukri", {})
    naukri_enabled = naukri_cfg.get("enabled", True) and platform_name in ("all", "naukri")
    naukri_max = naukri_cfg.get("max_daily_applications", 50)
    naukri_today = db.get_daily_applied_count("naukri")
    if naukri_enabled:
        if db.is_daily_limit_reached("naukri") or naukri_today >= naukri_max:
            logger.info(f"Naukri daily quota already reached for today ({naukri_today}/{naukri_max}). Skipping Naukri.")
        else:
            active_platforms.append("naukri")

    if not active_platforms:
        logger.warning("Both LinkedIn and Naukri have reached their daily quotas for today. Stopping.")
        show_stats(db)
        return

    # Dual-Platform Cascading & Interleaved Execution
    logger.info(f"Active platforms for today's run: {', '.join(p.upper() for p in active_platforms)}")

    linkedin_platform = LinkedInPlatform(config, db, headless=headless) if "linkedin" in active_platforms else None
    naukri_platform = NaukriPlatform(config, db, headless=headless) if "naukri" in active_platforms else None

    # Cascade Left-to-Right: First try fresh 24h postings. If quota remaining, cascade to 7d.
    for t_window in time_windows:
        if not active_platforms:
            logger.success("All platform daily limits reached or exceeded! Stopping application run.")
            break

        logger.step("=======================================================")
        logger.step(f"Searching Time Window: '{t_window}' (Left-to-Right Cascading Strategy)")
        logger.step("=======================================================")

        for keyword in search_keywords:
            if not active_platforms:
                break

            logger.step(f"--- Targeting Role: '{keyword}' [Window: {t_window}] across {len(search_locations)} locations ---")

            # 1. Apply on LinkedIn for this role
            if "linkedin" in active_platforms and linkedin_platform:
                cur_l_count = db.get_daily_applied_count("linkedin")
                if db.is_daily_limit_reached("linkedin") or cur_l_count >= linkedin_max or linkedin_platform.limit_reached:
                    logger.warning(f"LinkedIn daily limit exceeded ({cur_l_count}/{linkedin_max}). Closing LinkedIn portal for today.")
                    if "linkedin" in active_platforms:
                        active_platforms.remove("linkedin")
                else:
                    logger.step(f"--- Applying on LinkedIn for '{keyword}' ({t_window}) ---")
                    linkedin_platform.run(
                        keyword_override=[keyword],
                        location_override=search_locations,
                        time_filter_override=t_window,
                    )
                    if linkedin_platform.limit_reached or db.is_daily_limit_reached("linkedin") or db.get_daily_applied_count("linkedin") >= linkedin_max:
                        logger.warning("LinkedIn daily application limit reached! Closed LinkedIn for today. Continuing with remaining platforms.")
                        if "linkedin" in active_platforms:
                            active_platforms.remove("linkedin")

            # 2. Apply on Naukri for this role
            if "naukri" in active_platforms and naukri_platform:
                cur_n_count = db.get_daily_applied_count("naukri")
                if db.is_daily_limit_reached("naukri") or cur_n_count >= naukri_max or naukri_platform.limit_reached:
                    logger.warning(f"Naukri daily limit exceeded ({cur_n_count}/{naukri_max}). Closing Naukri portal for today.")
                    if "naukri" in active_platforms:
                        active_platforms.remove("naukri")
                else:
                    logger.step(f"--- Applying on Naukri for '{keyword}' ({t_window}) ---")
                    naukri_platform.run(
                        keyword_override=[keyword],
                        location_override=search_locations,
                        time_filter_override=t_window,
                    )
                    if naukri_platform.limit_reached or db.is_daily_limit_reached("naukri") or db.get_daily_applied_count("naukri") >= naukri_max:
                        logger.warning("Naukri daily application limit reached! Closed Naukri for today. Continuing with remaining platforms.")
                        if "naukri" in active_platforms:
                            active_platforms.remove("naukri")

    if not active_platforms:
        logger.success("Daily limits reached on all active platforms for today. Application cycle complete.")
    else:
        logger.success("Completed application cycle across all target positions.")

    show_stats(db)


def execute_job_list(
    position: Optional[Any] = None,
    location: Optional[Any] = None,
    platform_name: str = "all",
    time_filter: Optional[Any] = None,
    headless: bool = True,
    auto_apply: bool = False,
):
    """Searches and displays live job listings for one or multiple positions with left-to-right cascading time filters."""
    config = load_config()
    db = JobDatabase()

    search_keywords = normalize_positions(position, config)
    search_locations = normalize_locations(location, config)
    time_windows = normalize_time_filters(time_filter, config)

    console.print(
        Panel(
            f"[bold]Fetching Job Listings[/bold]\n"
            f"• Position(s): [bold green]{', '.join(search_keywords)}[/bold green]\n"
            f"• Location(s): [cyan]{', '.join(search_locations)}[/cyan]\n"
            f"• Time Window(s): [yellow]{' -> '.join(time_windows)}[/yellow] (Cascading Left-to-Right)\n"
            f"• Platforms: [magenta]{platform_name.upper()}[/magenta]",
            title="Job Search & Filter",
            border_style="cyan",
        )
    )

    all_jobs = []
    seen_keys = set()
    matched_window = time_windows[0]

    for t_window in time_windows:
        logger.step(f"Searching listings for window: '{t_window}'...")
        for keyword in search_keywords:
            for loc in search_locations:
                if platform_name in ("all", "linkedin"):
                    linkedin = LinkedInPlatform(config, db, headless=headless)
                    l_jobs = linkedin.list_jobs(keyword, loc, time_filter=t_window)
                    for j in l_jobs:
                        key = (j["id"], "linkedin")
                        if key not in seen_keys:
                            seen_keys.add(key)
                            all_jobs.append(j)

                if platform_name in ("all", "naukri"):
                    naukri = NaukriPlatform(config, db, headless=headless)
                    n_jobs = naukri.list_jobs(keyword, loc, time_filter=t_window)
                    for j in n_jobs:
                        key = (j["id"], "naukri")
                        if key not in seen_keys:
                            seen_keys.add(key)
                            all_jobs.append(j)

        if all_jobs:
            matched_window = t_window
            break
        elif len(time_windows) > 1:
            logger.info(f"No matching jobs found in '{t_window}'. Cascading left-to-right to next window...")

    if not all_jobs:
        logger.warning(
            f"No job listings found for {search_keywords} in {search_locations} with filter(s) '{' -> '.join(time_windows)}'."
        )
        return

    # Render formatted listings table
    table = Table(
        title=f"Matching Jobs for {', '.join(search_keywords)} (Matched Window: {matched_window})",
        border_style="blue",
        show_lines=True,
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Title", style="bold cyan")
    table.add_column("Company", style="yellow")
    table.add_column("Location", style="white")
    table.add_column("Platform", style="magenta", justify="center")
    table.add_column("Posted", style="green")
    table.add_column("Type", style="cyan", justify="center")
    table.add_column("Status", justify="center")

    unapplied_count = 0
    for idx, job in enumerate(all_jobs, 1):
        if job["already_applied"]:
            status_str = "[bold dim red]Already Applied[/bold dim red]"
        else:
            status_str = "[bold green]Ready to Apply[/bold green]"
            unapplied_count += 1

        table.add_row(
            str(idx),
            job["title"][:32],
            job["company"][:22],
            job["location"][:18],
            job["platform"],
            job["posted_time"],
            job["apply_type"],
            status_str,
        )

    console.print(table)
    console.print(
        f"\n[bold]Summary:[/bold] Found [cyan]{len(all_jobs)}[/cyan] listings. "
        f"[green]{unapplied_count} new eligible jobs[/green] available to apply.\n"
    )

    # Prompt or proceed with apply
    if unapplied_count > 0:
        proceed = auto_apply
        if not proceed and sys.stdin.isatty():
            ans = input(
                f"Would you like to automatically apply to these {unapplied_count} jobs across {len(search_keywords)} positions now? [y/N]: "
            ).strip().lower()
            proceed = ans in ("y", "yes")

        if proceed:
            logger.info(f"Proceeding to auto-apply across {len(search_keywords)} target positions...")
            execute_job_apply(
                platform_name=platform_name,
                headless=headless,
                position=search_keywords,
                location=search_locations,
                time_filter=time_filter,
            )


def execute_workday_portal(
    url: str,
    position: Optional[Any] = None,
    location: Optional[Any] = "India",
    headless: bool = False,
    auto_apply: bool = False,
):
    """Directly scans any company's Workday career portal, filters relevant roles, and executes applications."""
    config = load_config()
    db = JobDatabase()
    positions = normalize_positions(position, config)
    locations = normalize_locations(location, config)
    loc_target = locations[0] if locations else "India"

    scanner = WorkdayPortalScanner(company_url=url, config=config, db=db, headless=headless)
    console.print(
        Panel(
            f"[bold]Direct Workday Career Portal Scanner[/bold]\n"
            f"• Company: [bold green]{scanner.company_name}[/bold green]\n"
            f"• Target Portal: [cyan]{url}[/cyan]\n"
            f"• Target Role(s): [bold green]{', '.join(positions)}[/bold green]\n"
            f"• Target Location: [yellow]{loc_target}[/yellow]\n"
            f"• Mode: [{'yellow]Background (Headless)' if headless else 'green]Visible Window'}[/]\n"
            f"• Auto-Apply: [{'bold green]ENABLED[/]' if auto_apply else '[dim yellow]Discovery Only (use --apply to submit)[/]'}",
            title="Workday Scanner",
            border_style="cyan",
        )
    )

    jobs = scanner.scan_jobs(keywords=positions, target_location=loc_target)
    if not jobs:
        logger.warning(f"No matching open roles found on {scanner.company_name} Workday portal for {positions}.")
        return

    scanner.display_jobs_table(jobs)

    eligible = [j for j in jobs if j.get("eligible")]
    if eligible:
        if auto_apply:
            applied = scanner.apply_to_jobs(jobs)
            logger.info(f"Successfully processed {applied} application(s) at {scanner.company_name}.")
        elif sys.stdin.isatty():
            choice = input(f"\nFound {len(eligible)} eligible role(s). Would you like to apply now with Fill-and-Review? [y/N]: ").strip().lower()
            if choice in ("y", "yes"):
                applied = scanner.apply_to_jobs(jobs)
                logger.info(f"Successfully processed {applied} application(s) at {scanner.company_name}.")


def execute_company_portal(
    url: str,
    position: Optional[Any] = None,
    location: Optional[Any] = "India",
    company: Optional[str] = None,
    headless: bool = False,
    auto_apply: bool = False,
):
    """Directly scans any company's career search portal (Deloitte, Workday, etc.), filters relevant roles, and executes applications."""
    config = load_config()
    db = JobDatabase()
    positions = normalize_positions(position, config)
    locations = normalize_locations(location, config)
    loc_target = locations[0] if locations else "India"

    from platforms.company_portal import CompanyPortalScanner
    scanner = CompanyPortalScanner(company_url=url, config=config, db=db, headless=headless, company_override=company)
    console.print(
        Panel(
            f"[bold]Company Career Portal Scanner[/bold]\n"
            f"• Company: [bold green]{scanner.company_name}[/bold green]\n"
            f"• Target Portal: [cyan]{url}[/cyan]\n"
            f"• Target Role(s): [bold green]{', '.join(positions)}[/bold green]\n"
            f"• Target Location: [yellow]{loc_target}[/yellow]\n"
            f"• Mode: [{'yellow]Background (Headless)' if headless else 'green]Visible Window'}[/]\n"
            f"• Auto-Apply: [{'bold green]ENABLED[/]' if auto_apply else '[dim yellow]Discovery Only (use --apply to submit)[/]'}",
            title="Company Portal Scanner",
            border_style="cyan",
        )
    )

    jobs = scanner.scan_jobs(keywords=positions, target_location=loc_target)
    if not jobs:
        logger.warning(f"No matching open roles found on {scanner.company_name} portal for {positions}.")
        return

    scanner.display_jobs_table(jobs)

    eligible = [j for j in jobs if j.get("eligible")]
    if eligible:
        if auto_apply:
            applied = scanner.apply_to_jobs(jobs)
            logger.info(f"Successfully processed {applied} application(s) at {scanner.company_name}.")
        elif sys.stdin.isatty():
            choice = input(f"\nFound {len(eligible)} eligible role(s). Would you like to apply now with Fill-and-Review? [y/N]: ").strip().lower()
            if choice in ("y", "yes"):
                applied = scanner.apply_to_jobs(jobs)
                logger.info(f"Successfully processed {applied} application(s) at {scanner.company_name}.")


def execute_apply_url(
    url: str,
    title: Optional[str] = None,
    company: Optional[str] = None,
    headless: bool = False,
    db: Optional[JobDatabase] = None,
):
    """Applies directly to any specific job posting URL (Deloitte, Lever, Greenhouse, Workday, etc.)."""
    import re
    import time

    config = load_config()
    db = db or JobDatabase()
    resume_path = get_resume_path(config)

    inferred_company = company or "Company"
    inferred_title = title if title else "DevOps Engineer"

    # Deduplication check
    if db.is_url_or_company_applied(job_url=url, company=inferred_company, title=inferred_title):
        logger.warning(f"This role ('{inferred_title}' at '{inferred_company}') has already been recorded in your database!")
        if sys.stdin.isatty():
            choice = input("Do you want to apply anyway? [y/N]: ").strip().lower()
            if choice not in ("y", "yes"):
                return

    ats_handler = ExternalATSHandler(config)
    browser_mgr = BrowserManager("direct_apply", headless=headless)
    try:
        page = browser_mgr.start()
        logger.step(f"Navigating to job posting: {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3.0)

        # Attempt to infer title from page heading ONLY if title was NOT provided by user
        if not title:
            try:
                h1 = page.locator("h1, .job-title, [data-automation-id='jobPostingHeader']").first
                c = h1.count()
                if isinstance(c, (int, float)) and c > 0:
                    t = h1.inner_text().strip()
                    if t and len(t) < 80:
                        inferred_title = t
            except Exception:
                pass

        # Check if the page is a Career Search Portal (e.g. Deloitte SuccessFactors or Workday)
        from platforms.company_portal import CompanyPortalScanner
        if CompanyPortalScanner.is_search_portal(page, url):
            logger.step(f"Detected Company Career Search Portal for '{inferred_company}' ({url})")
            logger.info(f"Targeting position(s): '{inferred_title}' on {inferred_company} portal...")
            browser_mgr.close()

            scanner = CompanyPortalScanner(
                company_url=url,
                config=config,
                db=db,
                headless=headless,
                company_override=company,
            )
            jobs = scanner.scan_jobs(keywords=[inferred_title], target_location="India")
            if not jobs:
                logger.warning(f"No matching open roles found on {inferred_company} portal for '{inferred_title}'.")
                return

            scanner.display_jobs_table(jobs)
            eligible = [j for j in jobs if j.get("eligible")]
            if eligible:
                logger.info(f"Found {len(eligible)} eligible role(s) to apply at {inferred_company} with Fill-and-Review.")
                applied = scanner.apply_to_jobs(jobs)
                logger.success(f"Processed {applied} application(s) at {inferred_company}.")
            return

        # Check if the page redirected to a generic root homepage or 404
        if hasattr(page, "url") and isinstance(page.url, str):
            current_url = page.url.lower().rstrip("/")
            from urllib.parse import urlparse
            parsed_current = urlparse(current_url)
            parsed_target = urlparse(url.lower().rstrip("/"))
            is_homepage = parsed_current.path in ("", "/", "/en.html", "/global/en.html", "/index.html", "/home") and parsed_target.path not in ("", "/", "/en.html", "/global/en.html")
            if is_homepage:
                logger.warning(
                    f"The target job URL redirected to a corporate homepage: {page.url}\n"
                    f"This usually means the job posting link is expired, inactive, or not a direct application link."
                )

        console.print(
            Panel(
                f"[bold green]Direct Job Application Engine[/bold green]\n"
                f"• Target URL: [cyan]{url}[/cyan]\n"
                f"• Inferred Role: [bold]{inferred_title}[/bold]\n"
                f"• Inferred Company: [yellow]{inferred_company}[/yellow]\n"
                f"• Candidate: [bold green]{config.get('profile', {}).get('full_name', 'Candidate')}[/bold green]\n"
                f"• Mode: [{'yellow]Background' if headless else 'green]Visible Window'}[/]",
                title="Direct Apply",
                border_style="green",
            )
        )

        cl_path = config.get("profile", {}).get("cover_letter_path", "cover_letter.pdf")
        resolved_cl = Path(cl_path)
        if not resolved_cl.is_absolute():
            resolved_cl = Path(__file__).parent.resolve() / resolved_cl

        success = ats_handler.apply_external(
            page=page,
            job_title=inferred_title,
            company=inferred_company,
            resume_path=resume_path,
            cover_letter_path=resolved_cl if resolved_cl.exists() else None,
        )

        if success:
            job_id_clean = re.sub(r"\W+", "_", f"{inferred_company}_{inferred_title}")[:30]
            db.record_application(
                job_id=job_id_clean,
                platform="direct",
                title=inferred_title,
                company=inferred_company,
                location="India",
                job_url=url,
                status="applied",
                reason="Applied via direct URL command",
            )
            logger.success(f"Successfully completed and recorded application for '{inferred_title}' at '{inferred_company}'!")
        else:
            logger.warning(f"Application was skipped or not submitted.")

    finally:
        browser_mgr.close()


def execute_resume_update(platform_name: str = "all", headless: bool = False):
    """Updates/bumps the latest resume on Naukri and LinkedIn to refresh profile timestamp."""
    config = load_config()
    db = JobDatabase()
    resume = get_resume_path(config)

    if not resume:
        logger.error(
            f"Cannot update profile: Resume file '{config.get('profile', {}).get('resume_path')}' not found."
        )
        return False

    console.print(
        Panel(
            f"[bold green]Profile & Resume Refresh Engine[/bold green]\n"
            f"• Resume File: [bold cyan]{resume.name}[/bold cyan]\n"
            f"• Purpose: Refreshes 'Profile Last Updated' timestamp to rank at top of recruiter searches.",
            title="Profile Refresh",
            border_style="green",
        )
    )

    if platform_name in ("all", "naukri") and config.get("platforms", {}).get("naukri", {}).get("enabled", True):
        np = NaukriPlatform(config, db, headless=headless)
        np.update_resume()

    if platform_name in ("all", "linkedin") and config.get("platforms", {}).get("linkedin", {}).get("enabled", True):
        lp = LinkedInPlatform(config, db, headless=headless)
        lp.update_resume()

    return True


def handle_login(platform_name: str):
    """Opens interactive visible browsers for the user to log in."""
    config = load_config()
    db = JobDatabase()

    if platform_name in ("all", "linkedin"):
        logger.step("Initiating LinkedIn interactive login...")
        lp = LinkedInPlatform(config, db, headless=False)
        lp.login()

    if platform_name in ("all", "naukri"):
        logger.step("Initiating Naukri interactive login...")
        np = NaukriPlatform(config, db, headless=False)
        np.login()


def show_stats(
    db: JobDatabase,
    show_all: bool = False,
    limit: Optional[int] = None,
    platform: str = "all",
    export_path: Optional[str] = None,
):
    """Renders formatted tables of application counts and applied jobs (supporting all records)."""
    stats = db.get_summary_stats()

    table = Table(title="Daily Application Quotas & Status", border_style="cyan")
    table.add_column("Platform", style="bold magenta")
    table.add_column("Applied Today", justify="center", style="bold green")
    table.add_column("Limit Status", justify="center")

    for p in ["linkedin", "naukri"]:
        p_stats = stats["today"].get(p, {"count": 0, "limit_reached": False})
        limit_badge = "[bold red]LIMIT REACHED[/bold red]" if p_stats["limit_reached"] else "[bold cyan]ACTIVE[/bold cyan]"
        table.add_row(p.capitalize(), str(p_stats["count"]), limit_badge)

    console.print(table)
    console.print(f"[bold]Total Successful Applications All-Time:[/bold] [green]{stats['total_all_time']}[/green]\n")

    # Determine fetch limit: None fetches all records without truncation
    fetch_limit = None if show_all else (limit if limit is not None else 10)
    records = db.get_recent_applications(limit=fetch_limit, platform=platform, status="applied")

    if records:
        if show_all or fetch_limit is None or fetch_limit >= len(records):
            title_text = f"All Applied Jobs ({len(records)} Total)"
        else:
            title_text = f"Recent Job Applications (Last {len(records)})"

        rec_table = Table(title=title_text, border_style="blue", show_lines=True)
        rec_table.add_column("#", style="dim", justify="right", width=4)
        rec_table.add_column("Title", style="bold cyan")
        rec_table.add_column("Company", style="yellow")
        rec_table.add_column("Platform", style="magenta", justify="center")
        rec_table.add_column("Location", style="white")
        rec_table.add_column("Status", justify="center")
        rec_table.add_column("Time", style="green")

        for idx, r in enumerate(records, 1):
            st = "[green]Applied[/green]" if r["status"] == "applied" else f"[red]{r['status']}[/red]"
            ts = r["timestamp"].replace("T", " ")[:16] if "T" in r.get("timestamp", "") else r.get("timestamp", "")
            rec_table.add_row(
                str(idx),
                r["title"][:34],
                r["company"][:24],
                r["platform"].capitalize(),
                r["location"][:18] or "-",
                st,
                ts,
            )
        console.print(rec_table)
        console.print(f"\n[bold]Total jobs displayed:[/bold] [green]{len(records)}[/green] out of [green]{stats['total_all_time']}[/green] all-time successful applications.\n")

        if export_path:
            import csv
            with open(export_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["job_id", "platform", "title", "company", "location", "status", "timestamp", "job_url"]
                )
                writer.writeheader()
                for r in records:
                    writer.writerow({k: r.get(k, "") for k in writer.fieldnames})
            logger.success(f"Exported {len(records)} applications to: {export_path}")


def setup_cron():
    """Generates and configures system cron entry for automatic daily execution."""
    config = load_config()
    cron_time = config.get("execution", {}).get("cron_time", "09:30")
    try:
        hour, minute = cron_time.split(":")
    except ValueError:
        hour, minute = "9", "30"

    base_dir = Path(__file__).parent.resolve()
    script_path = base_dir / "run_daily.sh"

    cron_line = f"{int(minute)} {int(hour)} * * * {script_path} --headless"

    console.print(
        Panel(
            f"[bold green]System Cron Setup for Daily Automation[/bold green]\n\n"
            f"Scheduled execution time: [cyan]{cron_time}[/cyan] daily\n"
            f"Executable script: [yellow]{script_path}[/yellow]\n\n"
            f"[bold]Cron Entry Line:[/bold]\n"
            f"[bold magenta]{cron_line}[/bold magenta]\n\n"
            f"This will run silently in background every day at {cron_time} until LinkedIn & Naukri daily limits are exceeded.",
            title="Cron Configuration",
            border_style="green",
        )
    )

    console.print("[bold]Options:[/bold]")
    console.print("  [1] Automatically install this entry to your crontab now")
    console.print("  [2] Print crontab command to copy-paste manually")
    console.print("  [3] Exit")

    choice = input("\nEnter choice [1/2/3] (default: 1): ").strip()
    if choice in ("", "1"):
        try:
            current_cron = subprocess.check_output("crontab -l 2>/dev/null || true", shell=True, text=True)
            if str(script_path) in current_cron:
                lines = [line for line in current_cron.splitlines() if str(script_path) not in line]
                current_cron = "\n".join(lines) + "\n"

            new_cron = current_cron.strip() + f"\n{cron_line}\n"
            proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
            proc.communicate(input=new_cron)
            if proc.returncode == 0:
                logger.success("Cron job installed successfully! The script will trigger daily automatically.")
            else:
                logger.error("Failed to update crontab.")
        except Exception as e:
            logger.error(f"Error setting up crontab: {e}")
    elif choice == "2":
        console.print(f"\nTo install manually, run:\n[bold yellow](crontab -l 2>/dev/null; echo \"{cron_line}\") | crontab -[/bold yellow]\n")


def main():
    parser = argparse.ArgumentParser(
        description="Automated job application system for LinkedIn & Naukri."
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    # 1. run command
    run_parser = subparsers.add_parser("run", help="Run automated job applications immediately")
    run_parser.add_argument(
        "--platform",
        choices=["linkedin", "naukri", "all"],
        default="all",
        help="Target platform (default: all)",
    )
    run_parser.add_argument(
        "--position",
        nargs="*",
        default=None,
        help="Target position(s) (e.g. --position 'DevOps Engineer' 'AWS Engineer' or 'DevOps, AWS')",
    )
    run_parser.add_argument(
        "--location",
        nargs="*",
        default=None,
        help="Target location(s) (e.g. --location 'Noida' 'Bengaluru' or 'Remote')",
    )
    run_parser.add_argument(
        "--time",
        nargs="*",
        default=None,
        help="Time window filter(s) for postings: e.g. --time 24h or --time 24h 7d (cascades left to right)",
    )
    run_parser.add_argument(
        "--headless",
        action="store_true",
        help="Force background execution (headless)",
    )
    run_parser.add_argument(
        "--visible",
        action="store_true",
        help="Force visible browser window",
    )

    # 2. list command (Search & view listings without applying)
    list_parser = subparsers.add_parser("list", help="Search & view live job listings with time filters")
    list_parser.add_argument(
        "--position",
        nargs="*",
        default=None,
        help="Target position(s) (e.g. --position 'DevOps Engineer' 'AWS Engineer' or 'DevOps, AWS')",
    )
    list_parser.add_argument(
        "--location",
        nargs="*",
        default=None,
        help="Target location(s) (e.g. --location 'Noida' 'Bengaluru' or 'Remote')",
    )
    list_parser.add_argument(
        "--platform",
        choices=["linkedin", "naukri", "all"],
        default="all",
        help="Platform to inspect (default: all)",
    )
    list_parser.add_argument(
        "--time",
        nargs="*",
        default=None,
        help="Filter jobs posted in: 24h, 7d, 15d, 30d (supports cascading left to right)",
    )
    list_parser.add_argument(
        "--apply",
        action="store_true",
        help="Auto-apply to the found unapplied jobs after displaying the list",
    )
    list_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run search headlessly in background",
    )
    list_parser.add_argument(
        "--visible",
        action="store_true",
        help="Run search with visible browser window",
    )

    # 3. login command
    login_parser = subparsers.add_parser("login", help="Open visible browser to log into platforms")
    login_parser.add_argument(
        "--platform",
        choices=["linkedin", "naukri", "all"],
        default="all",
        help="Platform to log in (default: all)",
    )

    # 4. stats command
    stats_parser = subparsers.add_parser("stats", help="Display daily quotas and application history")
    stats_parser.add_argument(
        "--all",
        action="store_true",
        help="Show ALL applied jobs in the database (not just the last 10)",
    )
    stats_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Number of applied jobs to display (e.g. --limit 50)",
    )
    stats_parser.add_argument(
        "--platform",
        choices=["linkedin", "naukri", "all"],
        default="all",
        help="Filter applied jobs by platform (linkedin, naukri, all)",
    )
    stats_parser.add_argument(
        "--export",
        type=str,
        default=None,
        help="Export applied jobs to CSV file (e.g. --export applied_jobs.csv)",
    )

    # 5. cron-setup command
    subparsers.add_parser("cron-setup", help="Set up automatic daily Linux cron schedule")

    # 6. schedule command
    schedule_parser = subparsers.add_parser("schedule", help="Run in-process daemon scheduler")
    schedule_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run background scheduler headlessly",
    )

    # 7. update-resume command
    update_resume_parser = subparsers.add_parser(
        "update-resume", help="Upload latest resume to platforms to refresh 'Updated Today' timestamp"
    )
    update_resume_parser.add_argument(
        "--platform",
        choices=["linkedin", "naukri", "all"],
        default="all",
        help="Platform to update (default: all)",
    )
    update_resume_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run update headlessly in background",
    )
    update_resume_parser.add_argument(
        "--visible",
        action="store_true",
        help="Run update with visible browser window",
    )

    # 8. workday command
    workday_parser = subparsers.add_parser(
        "workday", help="Scan and apply directly on any company Workday career portal (e.g. Invesco, Accenture, Adobe)"
    )
    workday_parser.add_argument(
        "--url",
        required=True,
        type=str,
        help="Company Workday career portal URL (e.g. https://invesco.wd1.myworkdayjobs.com/IVZ)",
    )
    workday_parser.add_argument(
        "--position",
        nargs="*",
        default=None,
        help="Target position(s) (e.g. --position 'DevOps Engineer' 'AWS Engineer')",
    )
    workday_parser.add_argument(
        "--location",
        nargs="*",
        default=None,
        help="Target location(s) (default: India)",
    )
    workday_parser.add_argument(
        "--apply",
        action="store_true",
        help="Automatically apply to all discovered eligible jobs",
    )
    workday_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in background headless mode",
    )
    workday_parser.add_argument(
        "--visible",
        action="store_true",
        help="Run with visible browser window",
    )

    # 9. apply-url command (Universal Direct Job URL Applier, e.g. Deloitte, Lever, Avature)
    apply_url_parser = subparsers.add_parser(
        "apply-url", help="Apply directly to any specific job posting URL (e.g. Deloitte, Workday, Lever, Greenhouse)"
    )
    apply_url_parser.add_argument(
        "--url",
        required=True,
        type=str,
        help="Direct job posting URL (e.g. Deloitte or any company career posting)",
    )
    apply_url_parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Job title (optional, inferred from page if omitted)",
    )
    apply_url_parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Company name (optional, e.g. Deloitte)",
    )
    apply_url_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in background headless mode",
    )
    apply_url_parser.add_argument(
        "--visible",
        action="store_true",
        help="Run with visible browser window (default)",
    )

    # 10. portal command (Universal Company Career Portal Scanner, e.g. Deloitte, Workday, etc.)
    portal_parser = subparsers.add_parser(
        "portal", help="Scan and apply on any company career portal (e.g. Deloitte, Invesco, Accenture, Adobe)"
    )
    portal_parser.add_argument(
        "--url",
        required=True,
        type=str,
        help="Company career portal URL (e.g. https://southasiacareers.deloitte.com/go/Deloitte-India/718244/)",
    )
    portal_parser.add_argument(
        "--position",
        nargs="*",
        default=None,
        help="Target position(s) (e.g. --position 'DevOps Engineer' 'AWS Engineer')",
    )
    portal_parser.add_argument(
        "--location",
        nargs="*",
        default=None,
        help="Target location(s) (default: India)",
    )
    portal_parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Company name override (e.g. Deloitte)",
    )
    portal_parser.add_argument(
        "--apply",
        action="store_true",
        help="Automatically apply to all discovered eligible jobs",
    )
    portal_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in background headless mode",
    )
    portal_parser.add_argument(
        "--visible",
        action="store_true",
        help="Run with visible browser window",
    )

    args = parser.parse_args()
    config = load_config()
    db = JobDatabase()

    if args.command == "run":
        headless = determine_headless_mode(args, config)
        execute_job_apply(
            platform_name=args.platform,
            headless=headless,
            position=args.position,
            location=args.location,
            time_filter=args.time,
        )

    elif args.command == "list":
        headless = determine_headless_mode(args, config)
        execute_job_list(
            position=args.position,
            location=args.location,
            platform_name=args.platform,
            time_filter=args.time,
            headless=headless,
            auto_apply=args.apply,
        )

    elif args.command == "login":
        handle_login(args.platform)

    elif args.command == "stats":
        show_stats(
            db,
            show_all=getattr(args, "all", False),
            limit=getattr(args, "limit", None),
            platform=getattr(args, "platform", "all"),
            export_path=getattr(args, "export", None),
        )

    elif args.command == "cron-setup":
        setup_cron()

    elif args.command == "schedule":
        headless = getattr(args, "headless", True)
        cron_time = config.get("execution", {}).get("cron_time", "09:30")
        run_scheduler(
            lambda: execute_job_apply(platform_name="all", headless=headless),
            cron_time=cron_time,
        )

    elif args.command == "update-resume":
        headless = determine_headless_mode(args, config)
        execute_resume_update(platform_name=args.platform, headless=headless)

    elif args.command == "workday":
        headless = determine_headless_mode(args, config)
        execute_workday_portal(
            url=args.url,
            position=args.position,
            location=args.location,
            headless=headless,
            auto_apply=args.apply,
        )

    elif args.command == "portal":
        headless = determine_headless_mode(args, config)
        execute_company_portal(
            url=args.url,
            position=args.position,
            location=args.location,
            company=args.company,
            headless=headless,
            auto_apply=args.apply,
        )

    elif args.command == "apply-url":
        headless = getattr(args, "headless", False)
        execute_apply_url(
            url=args.url,
            title=args.title,
            company=args.company,
            headless=headless,
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
