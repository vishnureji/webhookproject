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
    cur = None  # FIX: initialise cur to None so finally block is always safe
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        article_id = data.get("id") or data.get("post_id")

        # FIX: guard against missing article_id before hitting the DB
        if not article_id:
            raise ValueError("Payload contains no usable article ID (id / post_id)")

        # FIX: created_ts must be an integer timestamp; coerce or discard
        raw_ts = data.get("created_ts")
        created_ts = int(raw_ts) if raw_ts is not None else None

        # FIX: serialise list/dict fields to JSON strings;
        #      pass None (→ SQL NULL) when the field is absent rather than
        #      json.dumps(None) which would insert the string "null"
        def to_json(val):
            return json.dumps(val) if val is not None else None

        cur.execute("""
    INSERT INTO articles_with_authors (
        article_id,
        headline,
        post_url,
        created_ts,
        updated_ts,
        author_id,
        displayname,
        photo,
        profile_url,
        last_modified
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
    ON CONFLICT (article_id) DO UPDATE SET
        headline      = EXCLUDED.headline,
        post_url      = EXCLUDED.post_url,
        created_ts    = EXCLUDED.created_ts,
        updated_ts    = EXCLUDED.updated_ts,
        author_id     = EXCLUDED.author_id,
        displayname   = EXCLUDED.displayname,
        photo         = EXCLUDED.photo,
        profile_url   = EXCLUDED.profile_url,
        last_modified = NOW();
""", (
    data.get("article_id"),
    data.get("headline"),
    data.get("post_url"),
    data.get("created_ts"),
    data.get("updated_ts"),
    data.get("author_id"),
    data.get("displayname"),
    data.get("photo"),
    data.get("profile_url"),
))
        conn.commit()
        logging.info(f"Successfully synced Article ID: {article_id}")

    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Database Error for ID {data.get('id', 'Unknown')}: {str(e)}")
        raise e

    finally:
        # FIX: close cur before conn, and check both independently
        if cur:
            cur.close()
        if conn:
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
