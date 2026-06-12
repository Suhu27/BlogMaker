# BlogMaker -- Daily AI Research Newsletter Generator

A production-ready Python application that generates daily research newsletters from topics stored in an Excel spreadsheet. Uses Google Gemini 2.5 Pro with web-grounded search for research, rule-based reliability scoring, and Resend for email delivery.

## Features

- **Automated research** via Gemini with Google Search grounding
- **Structured articles** with executive summary, key concepts, takeaways, counterpoints, LinkedIn angles
- **Rule-based reliability scoring** with 100+ domain classifications across 3 tiers
- **Multi-format output**: HTML newsletter, PDF, Markdown archive, sources.json, metadata.json
- **Email delivery** via Resend API with retry logic
- **Length enforcement** with automatic article expansion if below target
- **Source quality improvement** with follow-up institutional searches
- **Testing mode** for safe experimentation without modifying topics
- **Daily scheduler** for automated local execution
- **GitHub Actions** workflow for cloud automation
- **Cost tracking** of Gemini API token usage
- **Post-run reports** with full execution metrics

## Quick Start

```bash
# 1. Clone and set up
git clone <repo-url> && cd BlogMaker
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your GEMINI_API_KEY and RESEND_API_KEY
# Edit config.yaml with your recipient_email

# 3. Create example topics
python main.py --create-example

# 4. Validate setup
python main.py --dry-run

# 5. Run
python main.py
```

## Configuration

All settings in `config.yaml`:

| Setting | Default | Description |
|---------|---------|-------------|
| `article_words` | 1500 | Target word count (enforced within +/-10%) |
| `executive_summary_words` | 150 | Executive summary target |
| `key_takeaways` | 5 | Number of key takeaway bullets |
| `counterpoints` | 3 | Number of counterarguments |
| `linkedin_angles` | 3 | Number of LinkedIn content ideas |
| `enable_email` | true | Send newsletter via Resend |
| `enable_pdf` | true | Generate PDF (requires WeasyPrint system deps) |
| `testing_mode` | false | Generate outputs but never mark topics Done |
| `daily_run_time` | "07:00" | Time for scheduled execution (HH:MM) |
| `enable_cost_tracking` | true | Track Gemini token usage |

### API Keys

Store in `.env` file (never commit):
```
GEMINI_API_KEY=your_key_here
RESEND_API_KEY=your_key_here
```

## Usage

```bash
python main.py                          # Run pipeline once
python main.py --dry-run               # Validate without API calls
python main.py --schedule              # Run on daily schedule
python main.py --config custom.yaml    # Custom config file
python main.py --topics other.xlsx     # Custom topics file
python main.py --create-example        # Create example topics.xlsx
```

## Output Structure

```
output/YYYY-MM-DD/
  article.html       # Newsletter HTML
  article.md         # Markdown archive
  article.pdf        # PDF version (if enabled)
  sources.json       # Source details with tier/score/category
  metadata.json      # Article metadata + email delivery status
  run_report.json    # Full execution report
```

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```

## GitHub Actions Deployment

### 1. Add Repository Secrets

Go to **Settings > Secrets and variables > Actions** and add:
- `GEMINI_API_KEY` -- your Google Gemini API key
- `RESEND_API_KEY` -- your Resend API key

### 2. Enable Workflow

The workflow at `.github/workflows/daily_newsletter.yml` runs daily at 07:00 UTC. It:
1. Checks out the repository
2. Installs Python and dependencies
3. Runs the newsletter pipeline
4. Commits updated `topics.xlsx` and outputs back to the repo

### 3. Manual Trigger

Go to **Actions > Daily Newsletter Generation > Run workflow** to trigger manually.

### 4. Monitoring

- Check **Actions** tab for run history
- Each run commits outputs to `output/YYYY-MM-DD/`
- `run_report.json` contains success/failure status and warnings
- Failed email delivery will NOT mark topics as Done (preventing data loss)

## Architecture

```
main.py                    -- CLI entry point + scheduler
src/
  config.py               -- YAML + env config with validation
  models.py               -- Article, Source, DeliveryResult, RunReport
  search_providers.py      -- Abstract search provider interface
  researcher.py            -- Gemini grounded search + follow-up
  article_generator.py     -- Structured generation + length enforcement
  reliability_scorer.py    -- Rule-based 100+ domain scoring
  html_renderer.py         -- Jinja2 template rendering
  pdf_generator.py         -- WeasyPrint with graceful fallback
  markdown_writer.py       -- Markdown archive writer
  output_manager.py        -- Output saving + validation
  email_sender.py          -- Resend with DeliveryResult tracking
  logger.py                -- Structured logging
tests/
  test_models.py           -- Source normalization, dataclass tests
  test_reliability_scorer.py -- Domain scoring, tier classification
  test_config.py           -- Config validation rules
  test_excel_handler.py    -- Read/write/sequential processing
  test_output.py           -- Output validation, run reports
```

## Key Design Decisions

- **Topic marked Done ONLY after email success** (when email enabled) -- prevents data loss
- **Rule-based scoring** -- deterministic, no LLM involvement in reliability scores
- **10% length tolerance** -- articles auto-expand if too short
- **Follow-up searches** -- if <30% high-quality sources, issues targeted institutional search
- **Testing mode** -- full pipeline execution without modifying Excel
- **Search provider abstraction** -- ready for Tavily/Serper/custom providers

## Requirements

- Python 3.11+
- Google Gemini API key
- Resend API key (for email delivery)
- WeasyPrint system dependencies (optional, for PDF generation)
