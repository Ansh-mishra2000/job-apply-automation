"""
Script to generate the comprehensive User Guide PDF for the Job Apply Automation tool.
Uses Playwright to render styled HTML to a perfectly balanced 4-page PDF document.
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
    margin: 14mm 14mm 14mm 14mm;
    @bottom-right {
      content: "Page " counter(page) " of " counter(pages);
      font-family: 'Inter', sans-serif;
      font-size: 8.5pt;
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
    line-height: 1.5;
    font-size: 9pt;
  }

  .page {
    page-break-after: always;
    display: flex;
    flex-direction: column;
  }

  .page:last-child {
    page-break-after: avoid;
  }

  /* Header Banner */
  .header-banner {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 50%, #0d9488 100%);
    color: #ffffff;
    padding: 20px 22px;
    border-radius: 8px;
    margin-bottom: 16px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.06);
  }

  .header-banner h1 {
    font-size: 18pt;
    font-weight: 800;
    letter-spacing: -0.5px;
    margin-bottom: 4px;
  }

  .header-banner p {
    font-size: 10pt;
    opacity: 0.92;
    margin-bottom: 10px;
  }

  .badges {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .badge {
    background: rgba(255, 255, 255, 0.2);
    border: 1px solid rgba(255, 255, 255, 0.35);
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 7.5pt;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }

  h2 {
    font-size: 12.5pt;
    font-weight: 700;
    color: #1e3a8a;
    border-bottom: 1.5px solid #e2e8f0;
    padding-bottom: 4px;
    margin-top: 14px;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  h3 {
    font-size: 10pt;
    font-weight: 600;
    color: #2c5282;
    margin-top: 10px;
    margin-bottom: 4px;
  }

  p {
    margin-bottom: 8px;
  }

  code {
    font-family: 'Fira Code', monospace;
    font-size: 8.2pt;
    background: #f1f5f9;
    padding: 1px 4px;
    border-radius: 3px;
    color: #dc2626;
  }

  .cmd-block {
    background: #0f172a;
    color: #f8fafc;
    padding: 8px 12px;
    border-radius: 6px;
    font-family: 'Fira Code', monospace;
    font-size: 8pt;
    line-height: 1.45;
    margin: 6px 0 10px 0;
    border-left: 3px solid #0d9488;
    page-break-inside: avoid;
  }

  .cmd-block .comment { color: #64748b; }
  .cmd-block .prompt { color: #4ade80; user-select: none; }

  .alert-box {
    border-radius: 6px;
    padding: 8px 12px;
    margin: 8px 0;
    font-size: 8.5pt;
    page-break-inside: avoid;
  }

  .alert-info {
    background: #f0f9ff;
    border-left: 3px solid #0284c7;
    color: #0369a1;
  }

  .alert-success {
    background: #f0fdf4;
    border-left: 3px solid #16a34a;
    color: #15803d;
  }

  .alert-warning {
    background: #fffbeb;
    border-left: 3px solid #f59e0b;
    color: #b45309;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0;
    font-size: 8.2pt;
    page-break-inside: avoid;
  }

  th, td {
    padding: 6.5px 9px;
    border: 1px solid #cbd5e1;
    text-align: left;
  }

  th {
    background: #f1f5f9;
    font-weight: 700;
    color: #0f172a;
  }

  tr:nth-child(even) {
    background: #f8fafc;
  }

  .terminal-preview {
    background: #090d16;
    color: #cbd5e1;
    padding: 10px 12px;
    border-radius: 6px;
    font-family: 'Fira Code', monospace;
    font-size: 7.6pt;
    line-height: 1.38;
    margin: 6px 0 10px 0;
    border: 1px solid #1e293b;
    page-break-inside: avoid;
    white-space: pre;
    overflow-x: hidden;
  }

  .term-green { color: #4ade80; font-weight: bold; }
  .term-cyan { color: #38bdf8; }
  .term-yellow { color: #facc15; }
  .term-magenta { color: #c084fc; }
  .term-red { color: #f87171; font-weight: bold; }
  .term-dim { color: #64748b; }
  .term-bold { font-weight: bold; }

  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin: 8px 0;
  }

  .feature-card {
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 8px 10px;
    background: #f8fafc;
  }

  .feature-card h4 {
    color: #1e3a8a;
    margin-bottom: 2px;
    font-size: 8.8pt;
  }

  .feature-card p {
    font-size: 8pt;
    line-height: 1.35;
    color: #475569;
    margin-bottom: 0;
  }

  .step-number {
    display: inline-block;
    width: 18px;
    height: 18px;
    background: #1e3a8a;
    color: white;
    text-align: center;
    border-radius: 50%;
    font-size: 7.5pt;
    line-height: 18px;
    font-weight: bold;
    margin-right: 5px;
  }
</style>
</head>
<body>

  <!-- ==================== PAGE 1 ==================== -->
  <div class="page">
    <div class="header-banner">
      <h1>🚀 Job Apply Automation Engine</h1>
      <p>Complete Operational Manual, Command Reference & Execution Guide for LinkedIn & Naukri</p>
      <div class="badges">
        <span class="badge">LinkedIn Easy Apply</span>
        <span class="badge">Naukri Direct Apply</span>
        <span class="badge">Daily Limit Detection</span>
        <span class="badge">Zero-RAM Cron</span>
        <span class="badge">Stealth Anti-Bot</span>
      </div>
    </div>

    <h2>📌 1. System Overview & Key Capabilities</h2>
    <p>This application automates job applications across <strong>LinkedIn</strong> and <strong>Naukri</strong> every day. It searches matching openings, answers screening questionnaires, and applies until each platform's daily quota/limit is reached.</p>

    <div class="grid-2">
      <div class="feature-card">
        <h4>🔒 1-Time Interactive Login</h4>
        <p>Log in once in a visible browser. Session cookies and 2FA tokens are saved permanently in <code>data/browser_profiles/</code>. No plaintext passwords stored, zero ban risk.</p>
      </div>
      <div class="feature-card">
        <h4>🎯 Position & Freshness Filters</h4>
        <p>Target specific roles (e.g. <em>Python Developer</em>) and filter postings by when they emerged: <strong>24h</strong>, <strong>7d</strong>, <strong>15d</strong>, or <strong>30d</strong>.</p>
      </div>
      <div class="feature-card">
        <h4>🛑 Daily Limit Auto-Halt</h4>
        <p>Detects platform limit warnings (e.g. <em>"Easy Apply limit reached"</em> or <em>"Daily limit exceeded"</em>) and halts cleanly without risking account suspension.</p>
      </div>
      <div class="feature-card">
        <h4>⚡ Zero-RAM System Cron</h4>
        <p>No heavy background daemon. A lightweight system cron job starts at your scheduled time, applies until limits hit, and terminates immediately.</p>
      </div>
    </div>

    <h2>🛠️ 2. Quick-Start Setup (Only Done Once)</h2>

    <p><span class="step-number">1</span><strong>Place Your Resume PDF:</strong> Place your resume in the project directory named <code>resume.pdf</code> (or edit <code>profile.resume_path</code> in <code>config.yaml</code>).</p>

    <p><span class="step-number">2</span><strong>Configure Preferences in <code>config.yaml</code>:</strong> Set your target keywords, locations, compensation, notice period, and years of experience:</p>
    <div class="cmd-block">
      <span class="comment"># Edit your preferences and profile answers</span><br>
      <span class="prompt">$ </span>nano config.yaml
    </div>

    <p><span class="step-number">3</span><strong>Perform One-Time Interactive Login:</strong> Run the login command. A visible browser window will open. Log into LinkedIn and Naukri, complete any OTP/2FA, and press Enter in your terminal:</p>
    <div class="cmd-block">
      <span class="comment"># Open visible browser to authenticate both platforms</span><br>
      <span class="prompt">$ </span>./.venv/bin/python main.py login
    </div>

    <div class="alert-box alert-success">
      <strong>✔ Session Authenticated:</strong> Your cookies and session data are stored locally in <code>data/browser_profiles/</code>. Automated daily runs will never ask for your password again!
    </div>
  </div>

  <!-- ==================== PAGE 2 ==================== -->
  <div class="page">
    <h2>📋 3. Master Command Reference Guide</h2>
    <p>Every command available in the application, organized by operational goal:</p>

    <table>
      <thead>
        <tr>
          <th style="width: 22%;">Goal / Task</th>
          <th style="width: 48%;">Command Syntax</th>
          <th style="width: 30%;">Behavior</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Interactive Apply</strong></td>
          <td><code>./.venv/bin/python main.py run</code></td>
          <td>Prompts for Visible vs Background. Applies until limits hit.</td>
        </tr>
        <tr>
          <td><strong>Target Specific Role</strong></td>
          <td><code>./.venv/bin/python main.py run --position "Python Developer" --time 24h</code></td>
          <td>Applies to that exact title posted in the last 24 hours.</td>
        </tr>
        <tr>
          <td><strong>Apply (15-Day Filter)</strong></td>
          <td><code>./.venv/bin/python main.py run --position "Backend Engineer" --time 15d</code></td>
          <td>Applies to jobs emerged across the last 15 days.</td>
        </tr>
        <tr>
          <td><strong>Visible Browser Run</strong></td>
          <td><code>./.venv/bin/python main.py run --visible</code></td>
          <td>Shows the browser window live on screen.</td>
        </tr>
        <tr>
          <td><strong>Background / Headless</strong></td>
          <td><code>./.venv/bin/python main.py run --headless</code></td>
          <td>Runs silently in background with minimal resource usage.</td>
        </tr>
        <tr>
          <td><strong>Single Platform Only</strong></td>
          <td><code>./.venv/bin/python main.py run --platform linkedin</code></td>
          <td>Runs only on LinkedIn (or <code>--platform naukri</code>).</td>
        </tr>
        <tr>
          <td><strong>View 24h Listings</strong></td>
          <td><code>./.venv/bin/python main.py list --position "Software Engineer" --time 24h</code></td>
          <td>Displays live matching table without auto-applying.</td>
        </tr>
        <tr>
          <td><strong>View 7d Listings</strong></td>
          <td><code>./.venv/bin/python main.py list --position "Python Developer" --time 7d</code></td>
          <td>Inspects matching jobs posted in the past 7 days.</td>
        </tr>
        <tr>
          <td><strong>View 15d Listings</strong></td>
          <td><code>./.venv/bin/python main.py list --position "Backend Developer" --time 15d</code></td>
          <td>Inspects matching jobs posted in the past 15 days.</td>
        </tr>
        <tr>
          <td><strong>View 30d Listings</strong></td>
          <td><code>./.venv/bin/python main.py list --position "Data Engineer" --time 30d</code></td>
          <td>Inspects matching jobs posted in the past 30 days.</td>
        </tr>
        <tr>
          <td><strong>Inspect & Auto-Apply</strong></td>
          <td><code>./.venv/bin/python main.py list --position "Python Developer" --time 24h --apply</code></td>
          <td>Fetches listings, shows table, then auto-applies.</td>
        </tr>
        <tr>
          <td><strong>Check Quotas & History</strong></td>
          <td><code>./.venv/bin/python main.py stats</code></td>
          <td>Shows today's application count, limit status, and past jobs.</td>
        </tr>
        <tr>
          <td><strong>Update Resume / Bump Profile</strong></td>
          <td><code>./.venv/bin/python main.py update-resume</code></td>
          <td>Re-uploads latest resume to update 'Active Today' profile timestamp.</td>
        </tr>
        <tr>
          <td><strong>Configure Daily Cron</strong></td>
          <td><code>./.venv/bin/python main.py cron-setup</code></td>
          <td>Installs automatic zero-RAM daily cron job.</td>
        </tr>
      </tbody>
    </table>

    <div class="alert-box alert-info">
      <strong>💡 Display Mode Prompt:</strong> Whenever you run <code>./.venv/bin/python main.py run</code> without <code>--headless</code> or <code>--visible</code>, the tool asks interactively:<br>
      <code>[1] Visible Window (watch in real-time) | [2] Background (silent, headless)</code>
    </div>
  </div>

  <!-- ==================== PAGE 3 ==================== -->
  <div class="page">
    <h2>🔍 4. Example: Inspecting Live Listings with Time Filters</h2>
    <p>Before applying, you can search and preview matching openings emerged in the last 24h, 7d, 15d, or 30d:</p>
    <div class="cmd-block">
      <span class="prompt">$ </span>./.venv/bin/python main.py list --position "Python Developer" --time 24h
    </div>

    <div class="terminal-preview">
<span class="term-bold term-cyan">Matching Jobs for 'Python Developer' (Last 24h)</span>
---------------------------------------------------------------------------------------------
<span class="term-dim"> # | Title                  | Company   | Location   | Platform | Posted | Type        | Status</span>
---+------------------------+-----------+------------+----------+--------+-------------+-----------------
<span class="term-dim"> 1</span> | Python Backend Eng.    | Razorpay  | Bengaluru  | LinkedIn | 2h ago | Easy Apply  | <span class="term-green">Ready to Apply</span>
<span class="term-dim"> 2</span> | Python/Django Dev.     | Swiggy    | Remote     | LinkedIn | 4h ago | Easy Apply  | <span class="term-green">Ready to Apply</span>
<span class="term-dim"> 3</span> | Senior Python Engineer | Infosys   | Bengaluru  | Naukri   | Today  | Fast Apply  | <span class="term-green">Ready to Apply</span>
<span class="term-dim"> 4</span> | Full Stack Python Dev  | Cognizant | Hyderabad  | LinkedIn | 7h ago | Easy Apply  | <span class="term-red">Already Applied</span>

<span class="term-bold">Summary:</span> Found <span class="term-cyan">4</span> listings. <span class="term-green">3 new eligible jobs</span> available to apply.
Would you like to automatically apply to these 3 jobs now? [y/N]: <span class="term-yellow">y</span>
<span class="term-green">✔ [SUCCESS] Proceeding to auto-apply...</span>
    </div>

    <h2>⚙️ 5. Example: Real-Time Auto-Apply Execution</h2>
    <p>When executing an application run, the engine logs each step with human-like delays:</p>

    <div class="terminal-preview">
<span class="term-bold term-cyan">╭──────────────────────── Auto Apply Bot ────────────────────────╮</span>
<span class="term-cyan">│</span> <span class="term-bold">Starting Automated Job Application Engine</span>                     <span class="term-cyan">│</span>
<span class="term-cyan">│</span> • Target Position: <span class="term-yellow">Python Developer</span> | Time Filter: <span class="term-yellow">Last 24h</span>    <span class="term-cyan">│</span>
<span class="term-cyan">╰────────────────────────────────────────────────────────────────╯</span>
<span class="term-cyan">ℹ [INFO]</span> Using resume: <span class="term-green">resume.pdf</span>
<span class="term-magenta">➔ [STEP]</span> Searching LinkedIn jobs for 'Python Developer' [Filter: 24h]...
<span class="term-magenta">➔ [STEP]</span> Found Easy Apply: Python Backend Engineer at Razorpay
<span class="term-cyan">ℹ [INFO]</span> Auto-filling experience: Python -> 2 years | Notice period -> 30 days
<span class="term-green">✔ [SUCCESS] Successfully applied to Python Backend Engineer at Razorpay [1/50 today]</span>
<span class="term-dim">... applying card by card with human randomized delays (3-6s) ...</span>
<span class="term-yellow">⚠ [WARNING] LinkedIn daily Easy Apply limit reached!</span>
<span class="term-cyan">ℹ [INFO]</span> Reached daily application limit target (50). Stopping.
<span class="term-magenta">➔ [STEP]</span> --- Starting Naukri Automation ---
<span class="term-green">✔ [SUCCESS] Successfully applied to Python Developer at TCS [1/50 today]</span>
<span class="term-yellow">⚠ [WARNING] Naukri daily application limit reached!</span>
    </div>
  </div>

  <!-- ==================== PAGE 4 ==================== -->
  <div class="page">
    <h2>⏰ 6. Setting Up Automatic Daily Zero-RAM Scheduling</h2>
    <p>To have the script run automatically every morning without keeping any window or terminal open:</p>
    
    <div class="cmd-block">
      <span class="prompt">$ </span>./.venv/bin/python main.py cron-setup
    </div>

    <p>This automatically installs this daily schedule entry into your system <code>crontab</code>:</p>
    <div class="cmd-block">
      30 9 * * * /home/ansh-mishra/Desktop/job apply script/run_daily.sh --headless
    </div>

    <div class="alert-box alert-info">
      <strong>💡 Zero-RAM Efficiency:</strong> Linux cron starts <code>run_daily.sh</code> silently in the background at 9:30 AM every morning. The script applies until LinkedIn and Naukri daily limits are exceeded, then completely shuts down, releasing <strong>100% of RAM</strong>.
    </div>

    <h2>📊 7. Monitoring Daily Quotas & Applied History</h2>
    <div class="cmd-block">
      <span class="prompt">$ </span>./.venv/bin/python main.py stats
    </div>
    <div class="terminal-preview">
<span class="term-bold term-cyan">     Daily Application Quotas & Status     </span>
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Platform ┃ Applied Today ┃ Limit Status ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ Linkedin │      50       │ <span class="term-red">LIMIT REACHED</span>│
│ Naukri   │      50       │ <span class="term-red">LIMIT REACHED</span>│
└──────────┴───────────────┴──────────────┘
<span class="term-bold">Total Successful Applications All-Time: 100</span>
    </div>

    <h2>🛡️ 8. Safety Best Practices</h2>
    <div class="alert-box alert-warning">
      <strong>Important Guidelines for Account Safety:</strong><br>
      • <strong>Do not set daily limits above 50-75</strong>: Platforms monitor burst activity. Safe limits are 40-50/day.<br>
      • <strong>Preserve your session</strong>: Avoid frequently clearing <code>data/browser_profiles/</code>.<br>
      • <strong>Update skills in <code>config.yaml</code></strong>: Ensure your skill years accurately reflect your experience for questionnaire auto-filling.
    </div>
  </div>

</body>
</html>
"""

def generate_pdf(output_path: str = "Job_Apply_Automation_Guide.pdf"):
    print(f"Rendering PDF guide to: {output_path}")
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
                "top": "12mm",
                "bottom": "12mm",
                "left": "12mm",
                "right": "12mm",
            },
        )
        browser.close()

    print(f"✔ Successfully created: {target_file.name} ({target_file.stat().st_size} bytes)")


if __name__ == "__main__":
    generate_pdf()
