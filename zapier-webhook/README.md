# Crawl4AI Zapier Webhook Server

Flask webhook server untuk integrasi Crawl4AI dengan Zapier (5000+ apps).

## Deploy Cepat

### Render (1-click)
1. Push repo ke GitHub
2. https://render.com → New Web Service
3. Hubungkan repo, set **Root Directory** ke `zapier-webhook`
4. Render auto-detect `render.yaml`

### Railway
```bash
railway up --service crawl4ai-zapier
```

### Manual
```bash
cd zapier-webhook
pip install -r requirements.txt
gunicorn server:app --bind 0.0.0.0:5000 --workers 2
```

## Setup di Zapier

### SKENARIO 1: Zapier → Crawl4AI (Action)
Crawl website sebagai **Action** dalam Zap.

1. Buat Zap baru di https://zapier.com
2. Trigger: pilih app apapun (Schedule, Email, Form, dll)
3. Action: pilih **Webhooks by Zapier** → **POST**
4. URL: `https://server-url/webhook/catch`
5. Payload Type: JSON
6. Data:
```json
{
  "url": "https://example.com",
  "formats": ["markdown"]
}
```
7. Test → Response berisi `content`, `response_time`, `links_count`
8. Map response fields ke action berikutnya (Google Sheets, Slack, Email, dll)

### SKENARIO 2: Crawl4AI → Zapier (Trigger)
Crawl4AI mengirim hasil ke Zapier.

1. Buat Zap baru → Trigger: **Webhooks by Zapier** → **Catch Hook**
2. Copy webhook URL: `https://hooks.zapier.com/hooks/catch/...`
3. Kirim crawl request ke server dengan webhook URL:
```bash
curl -X POST https://server-url/webhook/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "zapier_respond_url": "https://hooks.zapier.com/hooks/catch/..."
  }'
```
4. Crawl4AI akan crawl dan kirim hasil ke Zapier

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/webhook/trigger` | Async crawl + send result to Zapier |
| POST | `/webhook/catch` | Sync crawl (Zapier Action) |
| GET | `/result/<task_id>` | Poll crawl result |
| GET | `/health` | Health check |

## Webhook Payload

### Request (send to webhook)
```json
{
  "url": "https://example.com",
  "formats": ["markdown", "html"],
  "zapier_respond_url": "https://hooks.zapier.com/hooks/catch/xxx/yyy"
}
```

### Response (received by Zapier)
```json
{
  "event": "crawl_complete",
  "task_id": "a1b2c3d4",
  "data": {
    "url": "https://example.com",
    "status": "success",
    "content": "# Page Title...",
    "format": "markdown",
    "response_time": 142,
    "links_count": 24
  },
  "timestamp": "2026-06-22T02:30:00Z"
}
```

## Testing

```bash
# Test health
curl https://server-url/health

# Test sync crawl (Zapier action)
curl -X POST https://server-url/webhook/catch \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Test async crawl with webhook
curl -X POST https://server-url/webhook/trigger \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Poll result
curl https://server-url/result/<task_id>
```

## Deploy ke Render (1-click)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://dashboard.render.com/blueprint/new?repo=https://github.com/ivansslo/crawl4ai)

**Setelah klik tombol di atas:**
1. Hubungkan GitHub repo `ivansslo/crawl4ai`
2. Set **Root Directory** → `zapier-webhook`
3. Render auto-detect `render.yaml`
4. Klik **Apply** → selesai! 🚀
