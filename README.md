# CV Status Checker

A tool that reads CV files from a Google Drive folder, extracts structured candidate data using Claude AI, sends tracked outreach emails via SendGrid, and monitors engagement (opens, clicks, replies) — automatically updating each candidate's status.

## Architecture

```
Google Drive folder
       │
       ▼
  CV files (PDF, DOCX, TXT, Google Docs)
       │
       ▼
  Text extraction (pdfplumber / python-docx)
       │
       ▼
  Claude AI parsing
  → name, email, phone, LinkedIn
  → years of experience
  → main skills + tech stack
  → business domain knowledge
  → work history + education
       │
       ▼
  SQLite database (candidates, templates, campaigns, events)
       │
       ├──▶ FastAPI REST API
       │         ├── /api/candidates   — search, filter, update status
       │         ├── /api/emails       — manage templates, send outreach
       │         └── /api/track        — tracking pixel + webhooks
       │
       └──▶ SendGrid
                 ├── HTML email with tracking pixel
                 ├── Built-in open/click tracking
                 └── Inbound Parse (reply detection)
```

## Candidate Status Flow

```
PENDING → EMAILED → EMAIL_OPENED → REPLIED → INTERESTED
                                           → NOT_INTERESTED
```

Statuses are updated automatically when:
- An email is sent → `EMAILED`
- Tracking pixel fires or SendGrid reports open → `EMAIL_OPENED`
- SendGrid Inbound Parse detects a reply → `REPLIED`
- You manually update → any status

## Prerequisites

- Python 3.11+
- A [Google Cloud project](https://console.cloud.google.com/) with Drive API enabled
- A [SendGrid](https://sendgrid.com/) account (free tier works)
- An [Anthropic API key](https://console.anthropic.com/)

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in all required values
```

### 3. Set up Google Drive access

**Option A — Service Account (recommended for production):**
1. In Google Cloud Console → IAM → Service Accounts → Create
2. Download the JSON key → save as `service-account.json`
3. Share your Drive folder with the service account email (Viewer role)

**Option B — OAuth (local development):**
1. In Google Cloud Console → APIs → OAuth 2.0 Client IDs → Desktop app
2. Download `credentials.json` to the project root
3. On first run the browser will open for authorization; `token.json` is saved automatically

### 4. Set up SendGrid

1. Create a free account at [sendgrid.com](https://sendgrid.com/)
2. Verify your sender email address
3. Create an API key with **Mail Send** permissions
4. **Enable Event Webhook** (Settings → Mail Settings → Event Webhook):
   - URL: `https://your-app.example.com/api/track/sendgrid`
   - Events: Delivered, Opens, Clicks, Bounces, Unsubscribes
5. **Enable Inbound Parse** for reply detection (Settings → Inbound Parse):
   - Add your domain and point MX records to `mx.sendgrid.net`
   - Destination URL: `https://your-app.example.com/api/track/reply`

> For local development, expose your server with [ngrok](https://ngrok.com/):
> `ngrok http 8000` — then set `APP_BASE_URL` to the ngrok URL.

### 5. Start the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs available at: http://localhost:8000/docs

## Usage

### Scan CVs from Google Drive

```bash
curl -X POST "http://localhost:8000/api/candidates/sync"
```

Options:
- `?force_reparse=true` — re-parse files already in the DB
- `?folder_id=<id>` — override the configured folder

### Search candidates

```bash
# All candidates
curl "http://localhost:8000/api/candidates"

# Filter by skill and experience
curl "http://localhost:8000/api/candidates?skill=Python&min_years=5"

# Filter by status
curl "http://localhost:8000/api/candidates?status=PENDING"

# Full-text search
curl "http://localhost:8000/api/candidates?q=fintech+microservices"

# Filter by business domain
curl "http://localhost:8000/api/candidates?domain=Fintech"
```

### Create an email template

```bash
curl -X POST "http://localhost:8000/api/emails/templates" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Senior Engineer Outreach",
    "subject": "Exciting opportunity for {{first_name}} — {{role}} at {{company}}",
    "body_html": "<p>Hi {{first_name}},</p><p>I came across your profile and was impressed by your {{years_of_experience}} years of experience with {{top_skills}}.</p><p>We have an exciting {{role}} opening at {{company}} that I think would be a great fit. Would you be open to a quick call to learn more?</p><p>Best,<br>{{sender_name}}</p>",
    "body_text": "Hi {{first_name}},\n\nI came across your profile and was impressed by your {{years_of_experience}} years of experience with {{top_skills}}.\n\nWe have an exciting {{role}} opening at {{company}} that I think would be a great fit. Would you be open to a quick call to learn more?\n\nBest,\n{{sender_name}}"
  }'
```

Available template variables:
| Variable | Description |
|---|---|
| `{{candidate_name}}` | Full name |
| `{{first_name}}` | First name only |
| `{{candidate_title}}` | Current job title |
| `{{candidate_company}}` | Current company |
| `{{years_of_experience}}` | Total years |
| `{{top_skills}}` | Top 5 skills, comma-separated |
| `{{sender_name}}` | Recruiter name (passed at send time) |
| `{{role}}` | Position being offered |
| `{{company}}` | Your company name |

### Send outreach email

```bash
# Single candidate
curl -X POST "http://localhost:8000/api/emails/send/<candidate_id>" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "<template_id>",
    "sender_name": "Alice Smith",
    "role": "Senior Backend Engineer",
    "company": "Acme Corp"
  }'

# Bulk send
curl -X POST "http://localhost:8000/api/emails/send-bulk" \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_ids": ["id1", "id2", "id3"],
    "template_id": "<template_id>",
    "sender_name": "Alice Smith",
    "role": "Senior Backend Engineer",
    "company": "Acme Corp"
  }'
```

### View campaign tracking

```bash
# All campaigns
curl "http://localhost:8000/api/emails/campaigns"

# Campaigns for a specific candidate
curl "http://localhost:8000/api/emails/campaigns?candidate_id=<id>"

# Campaign detail (open count, opened_at, replied_at)
curl "http://localhost:8000/api/emails/campaigns/<campaign_id>"
```

### Update candidate status manually

```bash
curl -X PATCH "http://localhost:8000/api/candidates/<id>" \
  -H "Content-Type: application/json" \
  -d '{"status": "INTERESTED"}'
```

Valid statuses: `PENDING`, `EMAILED`, `EMAIL_OPENED`, `REPLIED`, `INTERESTED`, `NOT_INTERESTED`

## Email Tracking Details

### How open tracking works

Every email contains a hidden 1×1 transparent GIF:
```html
<img src="https://your-app.example.com/api/track/open/{unique_token}.gif"
     width="1" height="1" style="display:none;" />
```

When the recipient opens the email and loads images, the server:
1. Receives the GET request
2. Records the IP address, User-Agent, and timestamp
3. Increments `open_count` on the campaign
4. Updates candidate status to `EMAIL_OPENED`
5. Returns the GIF immediately (no delay to the user)

### SendGrid built-in tracking

SendGrid also provides its own open and click tracking, delivered via the Event Webhook (`POST /api/track/sendgrid`). Both systems are active simultaneously for redundancy.

### Reply detection

When a candidate replies, SendGrid's Inbound Parse forwards the email to `POST /api/track/reply`. The system extracts the sender's email, finds the corresponding candidate, and updates status to `REPLIED`.

## API Reference

Interactive docs: http://localhost:8000/docs

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/candidates` | List/search candidates |
| `GET` | `/api/candidates/{id}` | Get candidate details |
| `PATCH` | `/api/candidates/{id}` | Update status |
| `DELETE` | `/api/candidates/{id}` | Remove candidate |
| `POST` | `/api/candidates/sync` | Scan Google Drive folder |
| `GET` | `/api/emails/templates` | List email templates |
| `POST` | `/api/emails/templates` | Create template |
| `PUT` | `/api/emails/templates/{id}` | Update template |
| `DELETE` | `/api/emails/templates/{id}` | Delete template |
| `POST` | `/api/emails/send/{candidate_id}` | Send to one candidate |
| `POST` | `/api/emails/send-bulk` | Send to multiple candidates |
| `GET` | `/api/emails/campaigns` | List sent campaigns |
| `GET` | `/api/emails/campaigns/{id}` | Campaign details |
| `GET` | `/api/track/open/{token}.gif` | Tracking pixel (email open) |
| `POST` | `/api/track/sendgrid` | SendGrid event webhook |
| `POST` | `/api/track/reply` | SendGrid inbound parse (reply) |
| `GET` | `/health` | Health check |
