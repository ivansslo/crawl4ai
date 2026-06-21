# Zapier Integration Guide for Crawl4AI

Connect Crawl4AI web crawler to 5000+ apps via Zapier webhooks.

## Setup

### 1. Create a Zapier Webhook Trigger

1. Go to [Zapier](https://zapier.com) and create a new Zap
2. Select **Webhooks by Zapier** as the Trigger app
3. Choose **Catch Hook** or **Catch Raw Hook** event
4. Copy the webhook URL provided by Zapier

### 2. Configure Crawl4AI to send to Zapier

```bash
POST /webhook/trigger
Content-Type: application/json

{
  "webhook_url": "https://hooks.zapier.com/hooks/catch/...",
  "url": "https://example.com",
  "formats": ["markdown"],
  "callback_data": {
    "zap_id": "my-zap-1",
    "notes": "Daily crawl"
  }
}
```

### 3. Zapier Action Examples

#### Example: Save crawl results to Google Sheets
- Trigger: Crawl4AI Webhook (Catch Hook)
- Action: Google Sheets → Create Spreadsheet Row
- Map: `url` → URL column, `content` → Content column, `response_time` → Speed column

#### Example: Send crawl results via Email
- Trigger: Crawl4AI Webhook (Catch Hook)  
- Action: Email by Zapier → Send Outbound Email
- Map: `data.content` → Email body, `data.url` → Subject

#### Example: Create Slack notification
- Trigger: Crawl4AI Webhook (Catch Hook)
- Action: Slack → Send Channel Message
- Map: `data.url` + "crawl completed" → Message text

### 4. Webhook Payload Format

```json
{
  "event": "crawl_complete",
  "data": {
    "url": "https://example.com",
    "status": "success",
    "content": "# Page Title\\n\\nContent here...",
    "format": "markdown",
    "response_time": 142,
    "links_count": 24
  },
  "callback": {
    "zap_id": "my-zap-1",
    "notes": "Daily crawl"
  }
}
```

## Auto-Trigger from Zapier (Reverse)

You can also trigger a crawl FROM Zapier:

1. Create a Zap with any trigger (Schedule, Email, Form, etc.)
2. Add **Webhooks by Zapier** → **Send Webhook** action
3. Set URL to: `https://your-crawl4ai-server.com/crawl`
4. Set Payload Type to JSON
5. Configure:
```json
{
  "url": "https://target-site.com",
  "formats": ["markdown", "html"]
}
```
6. Map the response to your next action

## Testing

```bash
# Test webhook endpoint
curl -X POST https://your-server.com/webhook/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "webhook_url": "https://hooks.zapier.com/hooks/catch/xxx/yyy",
    "url": "https://example.com"
  }'
```

## Deploy MCP Server

### Option 1: Render

1. Fork/push this repo to GitHub
2. Go to [Render](https://render.com) → New Web Service
3. Connect repo → Set `mcp-server` as root directory
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Option 2: Docker

```bash
docker build -t crawl4ai-mcp ./mcp-server
docker run -p 8000:8000 crawl4ai-mcp
```

### Option 3: Railway / Fly.io

Just point to the `mcp-server` directory with Python environment.
