import os
import logging
import json
import secrets
import psycopg2
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
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # ✅ Support both post_id and id
        post_id = data.get("post_id") or data.get("id")

        if not post_id:
            raise ValueError("Payload contains no usable article ID (id / post_id)")

        # ✅ Coerce timestamps to int
        created_ts = int(data.get("created_ts")) if data.get("created_ts") is not None else None
        updated_ts = int(data.get("updated_ts")) if data.get("updated_ts") is not None else None

        # ✅ Get authors array
        authors = data.get("authors", [])

        # ✅ If no authors, insert one row with null author fields
        if not authors:
            authors = [{}]

        # ✅ Loop through each author and insert one row per author
        for author in authors:
            cur.execute("""
                INSERT INTO articles_with_authors (
                    post_id,
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
                ON CONFLICT (post_id, author_id) DO UPDATE SET
                    headline      = EXCLUDED.headline,
                    post_url      = EXCLUDED.post_url,
                    created_ts    = EXCLUDED.created_ts,
                    updated_ts    = EXCLUDED.updated_ts,
                    displayname   = EXCLUDED.displayname,
                    photo         = EXCLUDED.photo,
                    profile_url   = EXCLUDED.profile_url,
                    last_modified = NOW();
            """, (
                post_id,
                data.get("headline"),
                data.get("post_url"),
                created_ts,
                updated_ts,
                author.get("author_id"),
                author.get("displayname"),
                author.get("photo"),
                author.get("profile_url"),
            ))

        conn.commit()
        logging.info(f"Successfully synced Post ID: {post_id} with {len(authors)} author(s)")

    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Database Error for ID {data.get('post_id', data.get('id', 'Unknown'))}: {str(e)}")
        raise e

    finally:
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
