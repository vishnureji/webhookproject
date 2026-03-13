import os
import logging
import json
import secrets
import psycopg2
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# --- LOGGING CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = FastAPI()
security = HTTPBasic()

# Configuration from Environment Variables
DB_URL = os.getenv("DATABASE_URL")
EXPECTED_USER = os.getenv("WEBHOOK_USER")
EXPECTED_PASS = os.getenv("WEBHOOK_PASS")


def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    """Verifies the Basic Auth credentials from RebelMouse."""
    if not EXPECTED_USER or not EXPECTED_PASS:
        logging.error("Webhook credentials not set in environment variables.")
        raise HTTPException(status_code=500, detail="Server configuration error")

    is_user_ok = secrets.compare_digest(credentials.username, EXPECTED_USER)
    is_pass_ok = secrets.compare_digest(credentials.password, EXPECTED_PASS)

    if not (is_user_ok and is_pass_ok):
        logging.warning(f"Unauthorized access attempt from user: {credentials.username}")
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def upsert_to_master(data):
    """Upserts RebelMouse post data and logs the process."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # ID Mapping
        article_id = data.get("id") or data.get("post_id")

        # Author Mapping
        author_ids = data.get("roar_author_ids", [])
        primary_author_id = author_ids[0] if author_ids else data.get("author_id")
        author_name = data.get("author_title") or data.get("author_name")

        # Date Mapping
        ts = data.get("created_ts")
        if ts:
            clean_pub_date = datetime.fromtimestamp(ts).date()
        else:
            raw_pub_date = data.get("publish_date") or data.get("publication_date")
            clean_pub_date = pd.to_datetime(raw_pub_date).date() if raw_pub_date else None

        cur.execute("""
        INSERT INTO articles_master (
            article_id,
            headline,
            subheadline,
            description,
            body,
            slug,
            post_url,
            image,
            created_ts,
            provider_id,
            public_tags,
            sections,
            listicle,
            roar_specific_data,
            last_modified
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT (article_id) DO UPDATE SET
            headline = EXCLUDED.headline,
            subheadline = EXCLUDED.subheadline,
            description = EXCLUDED.description,
            body = EXCLUDED.body,
            slug = EXCLUDED.slug,
            post_url = EXCLUDED.post_url,
            image = EXCLUDED.image,
            created_ts = EXCLUDED.created_ts,
            provider_id = EXCLUDED.provider_id,
            public_tags = EXCLUDED.public_tags,
            sections = EXCLUDED.sections,
            listicle = EXCLUDED.listicle,
            roar_specific_data = EXCLUDED.roar_specific_data,
            last_modified = NOW();
        """, (
            data.get("id"),
            data.get("headline"),
            data.get("subheadline"),
            data.get("description"),
            data.get("body"),
            data.get("manual_basename") or data.get("slug"),
            data.get("post_url"),
            data.get("image"),
            data.get("created_ts"),
            data.get("provider_id"),
            json.dumps(data.get("public_tags")),
            json.dumps(data.get("sections")),
            json.dumps(data.get("listicle")),
            json.dumps(data.get("roar_specific_data"))
        ))
        conn.commit()
        logging.info(f"Successfully synced Article ID: {article_id}")

    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Database Error for ID {data.get('id', 'Unknown')}: {str(e)}")
        raise e

    finally:
        if conn:
            cur.close()
            conn.close()


@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Webhook server is running"}


@app.post("/webhook")
async def rebelmouse_webhook(
    request: Request,
    authenticated_user: str = Depends(authenticate)
):
    try:
        payload = await request.json()

        logging.info(f"Authorized Webhook ({authenticated_user}): {json.dumps(payload)}")

        post_data = payload.get("post", payload)

        if not (post_data.get("id") or post_data.get("post_id")):
            logging.warning("Webhook received but missing Article ID.")
            return {"status": "ignored", "message": "Missing ID"}

        upsert_to_master(post_data)
        return {"status": "success", "message": "Article Synced"}

    except Exception as e:
        logging.critical(f"System Failure: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
