"""
Generates the comprehensive 'Tech_Stack_and_Architecture_Guide.pdf' document.
Uses Playwright to render a perfectly balanced, professional 5-page technical report detailing:
- Core stack & framework roles
- Alternatives matrix (Selenium, PostgreSQL, Celery, JSON, etc.)
- Architectural rationale (Why this stack was chosen)
- Application internal data flow and workflow
- Complete system installation guide from scratch
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Fira+Code:wght@400;500;600&display=swap');

  @page {
    size: A4;
    margin: 10mm 12mm 10mm 12mm;
    @bottom-right {
      content: "Page " counter(page) " of " counter(pages);
      font-family: 'Inter', sans-serif;
      font-size: 8pt;
      color: #64748b;
    }
  }

  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: #1e293b;
    background: #ffffff;
    line-height: 1.42;
    font-size: 8.5pt;
  }

  .page {
    page-break-after: always;
    display: flex;
    flex-direction: column;
    min-height: 100%;
    height: 100%;
    justify-content: flex-start;
  }

  .page:last-child {
    page-break-after: avoid;
  }

  /* Header Banner */
  .header-banner {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 50%, #0d9488 100%);
    color: #ffffff;
    padding: 16px 20px;
    border-radius: 8px;
    margin-bottom: 12px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.06);
  }

  .header-banner h1 {
    font-size: 16.5pt;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin-bottom: 4px;
  }

  .header-banner p {
    font-size: 8.5pt;
    color: #cbd5e1;
    line-height: 1.35;
  }

  .meta-tag-row {
    display: flex;
    gap: 8px;
    margin-top: 8px;
  }

  .meta-tag {
    background: rgba(255, 255, 255, 0.15);
    border: 1px solid rgba(255, 255, 255, 0.25);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 7.5pt;
    font-weight: 600;
    color: #f1f5f9;
  }

  h2 {
    font-size: 11pt;
    font-weight: 700;
    color: #0f172a;
    border-left: 4px solid #2563eb;
    padding-left: 8px;
    margin-top: 10px;
    margin-bottom: 6px;
    letter-spacing: -0.01em;
  }

  h3 {
    font-size: 9.5pt;
    font-weight: 600;
    color: #1e3a8a;
    margin-top: 6px;
    margin-bottom: 4px;
  }

  p {
    margin-bottom: 6px;
    color: #334155;
    text-align: justify;
  }

  /* Tables */
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 4px;
    margin-bottom: 8px;
    font-size: 7.6pt;
    background: #ffffff;
  }

  th {
    background: #f1f5f9;
    color: #0f172a;
    font-weight: 700;
    text-align: left;
    padding: 5px 7px;
    border: 1px solid #cbd5e1;
  }

  td {
    padding: 4.5px 7px;
    border: 1px solid #e2e8f0;
    color: #334155;
    vertical-align: top;
    line-height: 1.35;
  }

  tr:nth-child(even) td {
    background: #f8fafc;
  }

  /* Badge Styles */
  .badge {
    display: inline-block;
    padding: 1.5px 5px;
    border-radius: 3px;
    font-size: 6.8pt;
    font-weight: 600;
  }
  .badge-blue { background: #dbeafe; color: #1e40af; }
  .badge-emerald { background: #d1fae5; color: #065f46; }
  .badge-amber { background: #fef3c7; color: #92400e; }
  .badge-purple { background: #ede9fe; color: #5b21b6; }
  .badge-rose { background: #ffe4e6; color: #9f1239; }

  /* Callout Boxes */
  .alert-box {
    padding: 7px 11px;
    border-radius: 6px;
    margin-top: 6px;
    margin-bottom: 8px;
    font-size: 7.8pt;
    line-height: 1.38;
  }
  .alert-info {
    background: #f0f9ff;
    border-left: 4px solid #0284c7;
    color: #0369a1;
  }
  .alert-warning {
    background: #fffbeb;
    border-left: 4px solid #f59e0b;
    color: #92400e;
  }
  .alert-success {
    background: #f0fdf4;
    border-left: 4px solid #16a34a;
    color: #15803d;
  }

  /* Code Blocks */
  pre, code {
    font-family: 'Fira Code', Consolas, Monaco, monospace;
  }

  code {
    background: #f1f5f9;
    color: #0f172a;
    padding: 1px 3px;
    border-radius: 3px;
    font-size: 7.5pt;
  }

  .cmd-block {
    background: #0f172a;
    color: #e2e8f0;
    padding: 7px 11px;
    border-radius: 6px;
    font-family: 'Fira Code', monospace;
    font-size: 7.5pt;
    line-height: 1.4;
    margin-bottom: 7px;
    border: 1px solid #1e293b;
  }
  .cmd-block .prompt { color: #38bdf8; }
  .cmd-block .comment { color: #64748b; font-style: italic; }

  /* Grid Layouts */
  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-bottom: 6px;
  }

  .card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 7px 9px;
  }
  .card h4 {
    font-size: 8.2pt;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 3px;
  }

  .flow-step {
    display: flex;
    gap: 8px;
    margin-bottom: 6px;
  }
  .step-num {
    background: #2563eb;
    color: #ffffff;
    width: 19px;
    height: 19px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 7.2pt;
    flex-shrink: 0;
  }
  .step-content {
    font-size: 7.8pt;
    color: #334155;
    line-height: 1.38;
  }
  .step-content strong {
    color: #0f172a;
  }
</style>
</head>
<body>

  <!-- ======================================================================= -->
  <!-- PAGE 1: CORE STACK & COMPONENT RESPONSIBILITIES                         -->
  <!-- ======================================================================= -->
  <div class="page">
    <div class="header-banner">
      <h1>Technical Architecture & Stack Engineering Guide</h1>
      <p>Autonomous Job Application RPA Engine — Technology Selection, Comparative Analysis, and Deployment Reference</p>
      <div class="meta-tag-row">
        <span class="meta-tag">Python 3.10+</span>
        <span class="meta-tag">Playwright Chromium</span>
        <span class="meta-tag">SQLite 3 ACID</span>
        <span class="meta-tag">Rich Terminal UI</span>
        <span class="meta-tag">PyYAML Loader</span>
        <span class="meta-tag">Linux Zero-RAM Cron</span>
      </div>
    </div>

    <h2>1. Executive Summary & Core Tech Stack</h2>
    <p>
      This autonomous recruitment engine is an event-driven <strong>Robotic Process Automation (RPA)</strong> system designed to scale high-throughput job discovery, anti-bot navigation, heuristic candidate profile mapping, and 1-click submission across LinkedIn, Naukri, Workday, and enterprise ATS portals. The system operates on a zero-overhead architecture, ensuring zero memory leak, anti-bot evasion, and 100% data privacy.
    </p>

    <table>
      <thead>
        <tr>
          <th style="width: 17%;">Technology</th>
          <th style="width: 14%;">Ecosystem Layer</th>
          <th style="width: 21%;">Primary Module / File</th>
          <th>Functional Role & Implementation Details</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Python 3.10+</strong></td>
          <td><span class="badge badge-blue">Runtime & Core</span></td>
          <td><code>main.py</code>, All Modules</td>
          <td>Master orchestration language. Provides high-performance regex heuristics, asynchronous context handling, data structures, and cross-platform native APIs.</td>
        </tr>
        <tr>
          <td><strong>Playwright</strong></td>
          <td><span class="badge badge-emerald">Browser RPA</span></td>
          <td><code>utils/browser.py</code>, <code>platforms/</code></td>
          <td>Drives headless and visible Chromium browsers. Manages DOM locators, event dispatching, session cookies, multi-tab contexts, and CDP stealth injections.</td>
        </tr>
        <tr>
          <td><strong>SQLite 3</strong></td>
          <td><span class="badge badge-purple">Persistence</span></td>
          <td><code>database.py</code></td>
          <td>Transactional ACID application ledger (<code>data/jobs.db</code>). Enforces unique job deduplication, logs application history, and manages daily platform quotas.</td>
        </tr>
        <tr>
          <td><strong>Rich</strong></td>
          <td><span class="badge badge-amber">Terminal UI</span></td>
          <td><code>main.py</code>, <code>utils/logger.py</code></td>
          <td>CLI developer experience. Renders ANSI-styled application progress, live quota dashboards, formatted error banners, and ASCII application tables.</td>
        </tr>
        <tr>
          <td><strong>PyYAML</strong></td>
          <td><span class="badge badge-rose">Configuration</span></td>
          <td><code>config_loader.py</code></td>
          <td>Hierarchical configuration loader. Safely parses <code>config.yaml</code>, deep-merges user overrides with fallbacks, and loads cover letter text templates.</td>
        </tr>
        <tr>
          <td><strong>Linux Cron</strong></td>
          <td><span class="badge badge-blue">Scheduling</span></td>
          <td><code>run_daily.sh</code>, <code>main.py</code></td>
          <td>OS-level headless cron orchestrator. Executes daily at 9:30 AM, applies until daily limits are exhausted, and exits to free <strong>100% of RAM</strong>.</td>
        </tr>
        <tr>
          <td><strong>Python Unittest</strong></td>
          <td><span class="badge badge-emerald">QA & Testing</span></td>
          <td><code>tests/</code> (7 Test Suites)</td>
          <td>Comprehensive automated test runner. Evaluates 44 end-to-end and unit test cases covering ATS form filling, screening questions, rate limits, and stop criteria.</td>
        </tr>
      </tbody>
    </table>

    <h2>2. Architectural Component Breakdown</h2>
    <div class="grid-2">
      <div class="card">
        <h4>🤖 RPA & Browser Engine (Playwright)</h4>
        <p>
          Replaces fragile HTTP web-scraping with full JavaScript execution. Handles dynamic client-rendered frameworks (React, Angular) used by modern job boards. Injects stealth scripts to mask <code>navigator.webdriver</code> and prevent bot detection.
        </p>
      </div>
      <div class="card">
        <h4>🗄️ Application Ledger & Deduplication (SQLite)</h4>
        <p>
          Maintains an indexed local database of every discovered and applied job ID. Prevents re-visiting previously processed jobs across runs and records platform limits using atomic <code>ON CONFLICT</code> upserts.
        </p>
      </div>
      <div class="card">
        <h4>🧠 Heuristic Form Filler & Screening AI (Regex)</h4>
        <p>
          Analyzes complex question labels (e.g. CTC, notice period, years of AWS experience, legal sponsorship) and resolves exact choices via word-boundary fuzzy matching and numeric conversions.
        </p>
      </div>
      <div class="card">
        <h4>🌐 Universal ATS Dispatcher (Strategy Pattern)</h4>
        <p>
          Inspects target URLs and DOM signatures to identify Workday, Greenhouse, Lever, SmartRecruiters, or BambooHR, delegating to specialized multi-step form-filling handlers.
        </p>
      </div>
    </div>

    <div class="alert-box alert-info">
      <strong>Enterprise Modularity:</strong> Every layer is decoupled. If a new platform or ATS is added, you simply inherit from <code>BasePlatform</code> or extend <code>ExternalATSHandler</code> without rewriting database, logging, or browser management code.
    </div>
  </div>

  <!-- ======================================================================= -->
  <!-- PAGE 2: COMPARATIVE ANALYSIS MATRIX                                     -->
  <!-- ======================================================================= -->
  <div class="page">
    <h2>3. Comparative Technology Matrix: What Else Could We Use?</h2>
    <p>
      Every technology in this architecture was selected based on strict criteria: <strong>anti-bot resilience, memory efficiency, setup simplicity, zero cloud costs, and developer velocity</strong>. Below is a comprehensive evaluation of viable industry alternatives.
    </p>

    <table>
      <thead>
        <tr>
          <th style="width: 16%;">Category</th>
          <th style="width: 15%;">Chosen Solution</th>
          <th style="width: 25%;">Alternative Options</th>
          <th>Comparative Trade-offs & Why Chosen Won</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Browser RPA & Automation</strong></td>
          <td><strong>Playwright</strong></td>
          <td>• Selenium WebDriver<br>• Puppeteer (Node.js)<br>• Cypress<br>• Requests / Scrapy / BS4</td>
          <td>
            <strong>Selenium:</strong> Requires external webdriver binaries, prone to driver version mismatch, lacks native auto-waiting, easily fingerprinted by Akamai/Cloudflare.<br>
            <strong>Requests/Scrapy:</strong> Cannot execute JavaScript. Modern job sites (LinkedIn, Workday, Naukri) are heavy React/Angular SPAs requiring full DOM rendering.<br>
            <strong>Puppeteer:</strong> Excellent, but requires Node.js runtime, adding dual-language overhead when Python is preferred for data/NLP logic.<br>
            <strong>Playwright Won:</strong> Native Chrome DevTools Protocol WebSocket communication, 3x faster execution, built-in auto-waiting, and seamless session persistence.
          </td>
        </tr>
        <tr>
          <td><strong>Database & Persistence</strong></td>
          <td><strong>SQLite 3</strong></td>
          <td>• PostgreSQL / MySQL<br>• MongoDB<br>• Redis<br>• Flat JSON / CSV files</td>
          <td>
            <strong>Postgres/MySQL:</strong> Requires running a heavy background database server service (consuming 150MB+ RAM constantly) and user/password management.<br>
            <strong>Flat JSON/CSV:</strong> Prone to file corruption during unexpected termination and lacks atomic ACID locking and fast indexed lookups.<br>
            <strong>SQLite 3 Won:</strong> Built directly into Python standard library, zero background RAM, single-file backup (<code>data/jobs.db</code>), handles 100,000+ records with microsecond queries.
          </td>
        </tr>
        <tr>
          <td><strong>CLI & Terminal Experience</strong></td>
          <td><strong>Rich</strong></td>
          <td>• Python <code>print()</code> / Colorama<br>• Click / Typer<br>• Curses<br>• Tkinter / PyQt (GUI)<br>• Streamlit / Flask (Web)</td>
          <td>
            <strong>Click/Typer:</strong> Great for argument parsing, but lacks out-of-the-box styled tables, boxes, and live renderables.<br>
            <strong>Web/Desktop GUI:</strong> Adds unnecessary UI maintenance, increases attack surface, and cannot run headlessly over lightweight remote SSH servers.<br>
            <strong>Rich Won:</strong> Renders beautiful terminal UI tables and status panels with 0 web dependencies, zero HTTP ports, and minimal footprint.
          </td>
        </tr>
        <tr>
          <td><strong>Configuration Management</strong></td>
          <td><strong>PyYAML</strong></td>
          <td>• JSON (<code>config.json</code>)<br>• TOML (<code>pyproject.toml</code>)<br>• <code>.env</code> / Environment Variables<br>• INI files (<code>configparser</code>)</td>
          <td>
            <strong>JSON:</strong> Does not support comments (<code>#</code>), cannot format multiline string templates (cover letters) cleanly, and breaks on trailing commas.<br>
            <strong>.env:</strong> Flat key-value structure cannot represent nested objects like skill duration maps or list of target job keywords.<br>
            <strong>PyYAML Won:</strong> Supports clean hierarchical structures, comments, multiline text blocks, and is human-readable for non-technical candidates.
          </td>
        </tr>
        <tr>
          <td><strong>Scheduling & Execution</strong></td>
          <td><strong>Linux Cron</strong><br>(+ Python Schedule)</td>
          <td>• Celery + Celery Beat<br>• Apache Airflow<br>• systemd Timers<br>• Background <code>sleep()</code> Loop</td>
          <td>
            <strong>Celery/Airflow:</strong> Enterprise pipeline tools that require Redis/RabbitMQ message brokers and worker daemons consuming 500MB+ RAM 24/7.<br>
            <strong>Background <code>sleep()</code>:</strong> Wastes memory by keeping a full Python process idle in RAM all day.<br>
            <strong>Linux Cron Won:</strong> Consumes <strong>0 MB RAM</strong> all day. Starts the script at 9:30 AM, applies up to daily quotas, then shuts down cleanly.
          </td>
        </tr>
      </tbody>
    </table>

    <div class="alert-box alert-success">
      <strong>Core Architectural Principle:</strong> The chosen stack achieves the absolute highest performance and anti-bot stealth while requiring the lowest possible system resources (runs reliably on a 1 GB RAM cloud instance or local laptop).
    </div>
  </div>

  <!-- ======================================================================= -->
  <!-- PAGE 3: ARCHITECTURAL RATIONALE & BOT RESILIENCE                        -->
  <!-- ======================================================================= -->
  <div class="page">
    <h2>4. In-Depth Architectural Trade-offs</h2>
    <div class="grid-2">
      <div class="card">
        <h4>Selenium vs Playwright (The Decisive Choice)</h4>
        <p>
          Selenium communicates over HTTP requests through an intermediary driver binary (<code>chromedriver</code>), causing high latency, locator flakiness, and easy bot detection by Akamai and Cloudflare. <strong>Playwright connects directly via Chrome DevTools Protocol (CDP) WebSocket</strong>, offering 3x faster execution, built-in auto-waiting, and native browser context isolation.
        </p>
      </div>
      <div class="card">
        <h4>Why Pure HTTP (Requests/Scrapy) Fails for Jobs</h4>
        <p>
          Job application portals do not serve static HTML. LinkedIn's Easy Apply modal is dynamically rendered via WebSockets, and Workday uses complex shadow DOM structures and CSRF tokens tied to browser fingerprints. Pure HTTP requests trigger instant Cloudflare blocks and cannot upload resumes or interact with custom dynamic dropdowns.
        </p>
      </div>
    </div>

    <h2>5. Architectural Rationale: Why This Stack Fits the Role</h2>
    <p>
      Building an automated recruitment engine introduces distinct engineering challenges: <strong>evading strict bot detection algorithms</strong>, <strong>managing rolling platform quotas</strong>, <strong>preventing memory exhaustion</strong>, and <strong>safeguarding sensitive candidate credentials</strong>:
    </p>

    <div class="flow-step">
      <div class="step-num">1</div>
      <div class="step-content">
        <strong>Anti-Bot Evasion via Playwright Stealth & Persistent Contexts:</strong><br>
        Platforms like LinkedIn and Naukri actively monitor automation flags. We leverage Playwright’s <code>BrowserManager</code> to inject pre-execution JavaScript that removes the <code>navigator.webdriver</code> property and mocks audio/WebGL plugins. Utilizing persistent user data directories (<code>data/browser_profiles/</code>) preserves session cookies indefinitely, eliminating credential logins that trigger CAPTCHAs.
      </div>
    </div>

    <div class="flow-step">
      <div class="step-num">2</div>
      <div class="step-content">
        <strong>In-Place DOM Evaluation vs Destructive Navigation:</strong><br>
        Previous automation scripts navigated directly to <code>/jobs/view/{id}</code> using <code>page.goto()</code>, destroying the left search list and detaching virtual DOM elements. Our architecture executes in-place JavaScript dispatches: <code>card_loc.evaluate("el => el.click()")</code>. This preserves search pagination context and allows rapid 4-second Easy Apply cycles without page reload.
      </div>
    </div>

    <div class="flow-step">
      <div class="step-num">3</div>
      <div class="step-content">
        <strong>Micro-Footprint Data Integrity with SQLite WAL:</strong><br>
        The engine performs high-frequency read/write operations (checking if a job ID exists before clicking, then immediately recording the application). SQLite in Write-Ahead Logging (WAL) mode enables concurrent reads without blocking writes. Because all data resides in <code>data/jobs.db</code>, candidate records remain private and decoupled from cloud databases.
      </div>
    </div>

    <div class="flow-step">
      <div class="step-num">4</div>
      <div class="step-content">
        <strong>Non-Blocking I/O Multiplexing for External ATS Review:</strong><br>
        When external application auto-submit is disabled (<code>auto_submit: false</code>), traditional scripts freeze indefinitely on blocking <code>input()</code>. We architected non-blocking polling via Python’s <code>select.select([sys.stdin], [], [], timeout)</code>. If no input is received within 20 seconds, the bot automatically proceeds without hanging the browser process or causing session disconnects.
      </div>
    </div>

    <div class="flow-step">
      <div class="step-num">5</div>
      <div class="step-content">
        <strong>Dynamic Quota Detection & Graceful Platform Handover:</strong><br>
        When LinkedIn imposes its rolling daily anti-bot limit (e.g. <em>"We limit daily submissions to maintain quality and prevent bots..."</em>), the bot catches the inline banner or disabled button, sets <code>self.limit_reached = True</code>, updates SQLite, closes the LinkedIn browser, and seamlessly hands over execution to Naukri.
      </div>
    </div>
  </div>

  <!-- ======================================================================= -->
  <!-- PAGE 4: HOW THE ENGINE OPERATES (DATA FLOW)                             -->
  <!-- ======================================================================= -->
  <div class="page">
    <h2>6. Architectural Data Flow & Pipeline</h2>
    <div class="cmd-block">
<span class="prompt">User Config (config.yaml)</span> ─────────► <span class="comment">[ConfigLoader & Schema Merger]</span>
                                                    │
                                                    ▼
<span class="prompt">SQLite Ledger (data/jobs.db)</span> ◄──────── <span class="comment">[Platform Engine: LinkedIn / Naukri]</span>
  • Quota Check (Applied Today < 50)                │
  • Duplicate Job ID Lookup                         ▼
                                       <span class="comment">[Playwright Stealth Browser Context]</span>
                                         • In-place card click (JS dispatch)
                                         • Title & experience relevance filter
                                                    │
                                                    ▼
                                       <span class="comment">[Heuristic Question & ATS Filler]</span>
                                         • Regex field identification
                                         • Screening questionnaire resolver
                                         • Document attachment (resume.pdf)
                                                    │
                                                    ▼
                                       <span class="comment">[Submission & Anti-Bot Sentinel]</span>
                                         • Detects inline rate-limit banners
                                         • Marks SQLite status: LIMIT REACHED
                                         • Seamless handover to next platform
    </div>

    <h2>7. How the Application Works Internally (Lifecycle)</h2>
    <div class="flow-step">
      <div class="step-num">A</div>
      <div class="step-content">
        <strong>Configuration & Profile Ingestion:</strong><br>
        <code>config_loader.py</code> loads <code>config.yaml</code> and merges it recursively with <code>DEFAULT_CONFIG</code>. It resolves candidate metadata (Full Name, Experience, CTC, Skills duration map) and dynamically locates <code>resume.pdf</code> in the workspace.
      </div>
    </div>

    <div class="flow-step">
      <div class="step-num">B</div>
      <div class="step-content">
        <strong>Quota Verification & Database Sync:</strong><br>
        <code>JobDatabase</code> connects to <code>data/jobs.db</code>. It verifies whether LinkedIn or Naukri has already reached the daily limit for today’s date. If a platform is capped, it skips initialization entirely, avoiding unnecessary browser launch overhead.
      </div>
    </div>

    <div class="flow-step">
      <div class="step-num">C</div>
      <div class="step-content">
        <strong>Stealth Browser Initialization:</strong><br>
        <code>BrowserManager</code> launches Playwright Chromium with persistent user profiles located in <code>data/browser_profiles/{platform}</code>. It injects stealth JavaScript overrides into every page context to prevent anti-bot fingerprinting.
      </div>
    </div>

    <div class="flow-step">
      <div class="step-num">D</div>
      <div class="step-content">
        <strong>Deep Multi-Page Discovery & Filtering:</strong><br>
        The platform builder generates query URLs with specific parameters (e.g. <code>f_AL=true</code> for Easy Apply, <code>f_TPR=r2592000</code> for 30d freshness, and <code>start=0, 25, 50</code> across 3 pages). Cards are scanned and filtered using title relevance, 0-3 years experience thresholds, skill blacklists (SAP), and CV skill scoring.
      </div>
    </div>

    <div class="flow-step">
      <div class="step-num">E</div>
      <div class="step-content">
        <strong>Autonomous Form Execution (1-Click vs Multi-Step ATS):</strong><br>
        • <strong>LinkedIn Easy Apply:</strong> Fills multi-step modals, handles radio groups, selects dropdown options, uploads <code>resume.pdf</code>, and submits (taking ~4s per job).<br>
        • <strong>Naukri Direct Apply:</strong> Clicks fast apply and answers recruiter chatbot screening questions.<br>
        • <strong>External Portals:</strong> Detects Workday, Lever, or Greenhouse, auto-populates all contact fields, work history, and attaches resume and cover letter.
      </div>
    </div>

    <div class="flow-step">
      <div class="step-num">F</div>
      <div class="step-content">
        <strong>Database Ledger Update & Terminal Reporting:</strong><br>
        Upon successful submission, the job ID is recorded in <code>data/jobs.db</code> with timestamp, title, company, and URL. <code>main.py</code> renders an interactive <strong>Rich</strong> summary table displaying applied counts, remaining daily quota, and execution status.
      </div>
    </div>

    <h2>8. Safety, Throttling & Account Security</h2>
    <div class="grid-2">
      <div class="card">
        <h4>🛡️ Human-Like Action Delays</h4>
        <p>
          Between application steps and card clicks, the engine introduces randomized human delays (<code>3.0s – 6.5s</code>) to ensure API call patterns mirror natural browsing rhythms.
        </p>
      </div>
      <div class="card">
        <h4>🔒 Zero Cloud / Zero PII Leakage</h4>
        <p>
          All passwords, resumes, databases, and session tokens are strictly excluded from version control via <code>.gitignore</code>, ensuring candidate data never leaves the local machine.
        </p>
      </div>
    </div>
  </div>

  <!-- ======================================================================= -->
  <!-- PAGE 5: STEP-BY-STEP SYSTEM INSTALLATION GUIDE                          -->
  <!-- ======================================================================= -->
  <div class="page">
    <h2>9. How to Install & Configure on a Clean System</h2>
    <p>
      Follow this complete, step-by-step setup guide to prepare a fresh Linux/macOS/WSL system to execute the application autonomously:
    </p>

    <h3>Step 1: Install System Packages & Python 3.10+</h3>
    <div class="cmd-block">
      <span class="comment"># On Ubuntu / Debian / WSL2:</span><br>
      <span class="prompt">$ </span>sudo apt update && sudo apt install -y python3 python3-venv python3-pip git build-essential
    </div>

    <h3>Step 2: Clone Repository & Create Virtual Environment</h3>
    <div class="cmd-block">
      <span class="prompt">$ </span>git clone https://github.com/Ansh-mishra2000/job-apply-automation.git<br>
      <span class="prompt">$ </span>cd job-apply-automation<br>
      <span class="prompt">$ </span>python3 -m venv .venv<br>
      <span class="prompt">$ </span>source .venv/bin/activate
    </div>

    <h3>Step 3: Install Python Packages & Playwright Browser Binaries</h3>
    <p>
      Playwright requires Chromium browser binaries and system graphics/networking libraries:
    </p>
    <div class="cmd-block">
      <span class="prompt">$ </span>pip install -r requirements.txt<br>
      <span class="prompt">$ </span>playwright install chromium<br>
      <span class="prompt">$ </span>playwright install-deps chromium  <span class="comment"># Installs OS shared libraries for headless Chromium</span>
    </div>

    <h3>Step 4: Configure Personal Profile & Resume</h3>
    <div class="cmd-block">
      <span class="prompt">$ </span>cp config.example.yaml config.yaml<br>
      <span class="comment"># 1. Place your resume PDF in the project root directory named 'resume.pdf'</span><br>
      <span class="comment"># 2. Open config.yaml in your editor and update Name, Email, Phone, CTC, and Experience years.</span>
    </div>

    <h3>Step 5: Perform One-Time Platform Login</h3>
    <p>
      Opens visible browsers for you to log into LinkedIn and Naukri once. Session cookies are automatically preserved in <code>data/browser_profiles/</code> for all future headless runs:
    </p>
    <div class="cmd-block">
      <span class="prompt">$ </span>python main.py login --platform all
    </div>

    <h3>Step 6: Run Application Engine or Set Up Daily Cron</h3>
    <div class="grid-2">
      <div class="card">
        <h4>🚀 Manual Run Commands</h4>
        <div class="cmd-block" style="margin-bottom:0;">
          <span class="comment"># Visible execution:</span><br>
          <span class="prompt">$ </span>python main.py run --visible<br>
          <span class="comment"># Headless background run:</span><br>
          <span class="prompt">$ </span>python main.py run --headless<br>
          <span class="comment"># View quotas & applied history:</span><br>
          <span class="prompt">$ </span>python main.py stats
        </div>
      </div>
      <div class="card">
        <h4>⏰ Zero-RAM Daily Automation</h4>
        <div class="cmd-block" style="margin-bottom:0;">
          <span class="comment"># Installs Linux daily crontab entry:</span><br>
          <span class="prompt">$ </span>python main.py cron-setup<br>
          <span class="comment"># Crontab executes every morning at 9:30 AM:</span><br>
          30 9 * * * /path/to/run_daily.sh --headless
        </div>
      </div>
    </div>

    <div class="alert-box alert-success" style="margin-top: 8px;">
      <strong>✔ Ready to Scale:</strong> Once configured, the bot operates completely hands-free every morning, automatically applying up to 100 jobs daily across LinkedIn and Naukri and terminating cleanly upon quota completion.
    </div>
  </div>

</body>
</html>
"""

def generate_pdf(output_path: str = "Tech_Stack_and_Architecture_Guide.pdf"):
    print(f"Rendering Architecture & Tech Stack PDF guide to: {output_path}")
    base_dir = Path(__file__).parent.resolve()
    target_file = base_dir / output_path

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(HTML_CONTENT, wait_until="networkidle")
        page.pdf(
            path=str(target_file),
            format="A4",
            print_background=True,
            margin={
                "top": "8mm",
                "bottom": "8mm",
                "left": "10mm",
                "right": "10mm",
            },
        )
        browser.close()

    print(f"✔ Successfully created: {target_file.name} ({target_file.stat().st_size} bytes)")


if __name__ == "__main__":
    generate_pdf()
