# RebelMouse Webhook → PostgreSQL

FastAPI webhook that receives RebelMouse post events and upserts them into a PostgreSQL database.

## Deploy to Railway

### 1. Push this repo to GitHub

### 2. Create Railway project
- Go to railway.app → New Project → Deploy from GitHub repo
- Select this repo

### 3. Add PostgreSQL
- Inside your project → + New → Database → PostgreSQL
- Copy the DATABASE_URL from the Postgres Variables tab

### 4. Set environment variables (in your web service)
| Key           | Value                        |
|---------------|------------------------------|
| DATABASE_URL  | (copied from Postgres above) |
| WEBHOOK_USER  | your chosen username         |
| WEBHOOK_PASS  | your chosen password         |

### 5. Create the database table
- Click your Postgres service → Query tab
- Paste and run the contents of schema.sql

### 6. Get your URL
- Web service → Settings → Networking → Generate Domain

## Test

```bash
# Health check
curl https://yourapp.up.railway.app/

# Webhook test
curl -X POST https://yourapp.up.railway.app/webhook \
  -u USERNAME:PASSWORD \
  -H "Content-Type: application/json" \
  -d '{"post":{"id":1,"headline":"Test Article"}}'
```

## Endpoint

`POST /webhook` — Accepts RebelMouse post payloads, upserts to articles_master table.
`GET /`        — Health check.
