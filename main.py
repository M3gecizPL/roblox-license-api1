from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
import sqlite3
from datetime import datetime, timezone
import os

app = FastAPI()

DB_PATH = "licenses.db"

# Ten klucz będzie używany tylko przez Discord bota.
# Ustawisz go w Render Environment Variables jako ADMIN_API_KEY.
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "dev-test-key")


# =========================
# MODELE
# =========================

class LicenseCheck(BaseModel):
    product_id: str
    creator_type: str
    creator_id: int
    universe_id: int
    place_id: Optional[int] = None
    job_id: Optional[str] = None


class LicenseGrant(BaseModel):
    product_id: str
    roblox_user_id: int
    creator_type: str
    creator_id: int
    universe_id: int


class LicenseRevoke(BaseModel):
    product_id: str
    universe_id: int


# =========================
# DATABASE
# =========================

def get_conn():
    return sqlite3.connect(DB_PATH)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            roblox_user_id INTEGER NOT NULL,
            creator_type TEXT NOT NULL,
            creator_id INTEGER NOT NULL,
            universe_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL,
            revoked_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS license_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            creator_type TEXT,
            creator_id INTEGER,
            universe_id INTEGER,
            place_id INTEGER,
            job_id TEXT,
            result TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def log_check(data: LicenseCheck, result: str, reason: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO license_logs (
            product_id,
            creator_type,
            creator_id,
            universe_id,
            place_id,
            job_id,
            result,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.product_id,
        data.creator_type,
        data.creator_id,
        data.universe_id,
        data.place_id,
        data.job_id,
        result,
        reason,
        now_iso()
    ))

    conn.commit()
    conn.close()


def require_admin_key(x_api_key: Optional[str]):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


init_db()


# =========================
# PUBLICZNE ENDPOINTY
# =========================

@app.get("/")
def home():
    return {
        "ok": True,
        "message": "License API działa"
    }


@app.post("/license/check")
def check_license(data: LicenseCheck):
    print("License check:", data)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM licenses
        WHERE product_id = ?
          AND creator_type = ?
          AND creator_id = ?
          AND universe_id = ?
          AND status = 'ACTIVE'
        LIMIT 1
    """, (
        data.product_id,
        data.creator_type,
        data.creator_id,
        data.universe_id
    ))

    row = cur.fetchone()
    conn.close()

    if row:
        log_check(data, "ALLOW", "LICENSE_ACTIVE")
        return {
            "ok": True,
            "active": True,
            "reason": "LICENSE_ACTIVE"
        }

    log_check(data, "BLOCK", "NO_ACTIVE_LICENSE")
    return {
        "ok": True,
        "active": False,
        "reason": "NO_ACTIVE_LICENSE"
    }


# =========================
# ADMIN ENDPOINTY DLA DISCORD BOTA
# =========================

@app.post("/admin/license/grant")
def grant_license(data: LicenseGrant, x_api_key: Optional[str] = Header(default=None)):
    require_admin_key(x_api_key)

    if data.creator_type not in ["User", "Group"]:
        raise HTTPException(status_code=400, detail="creator_type must be User or Group")

    conn = get_conn()
    cur = conn.cursor()

    # Jeśli licencja już była, aktywujemy ją ponownie.
    cur.execute("""
        SELECT id FROM licenses
        WHERE product_id = ?
          AND universe_id = ?
        LIMIT 1
    """, (
        data.product_id,
        data.universe_id
    ))

    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE licenses
            SET roblox_user_id = ?,
                creator_type = ?,
                creator_id = ?,
                status = 'ACTIVE',
                revoked_at = NULL
            WHERE id = ?
        """, (
            data.roblox_user_id,
            data.creator_type,
            data.creator_id,
            existing[0]
        ))
    else:
        cur.execute("""
            INSERT INTO licenses (
                product_id,
                roblox_user_id,
                creator_type,
                creator_id,
                universe_id,
                status,
                created_at,
                revoked_at
            )
            VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, NULL)
        """, (
            data.product_id,
            data.roblox_user_id,
            data.creator_type,
            data.creator_id,
            data.universe_id,
            now_iso()
        ))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "message": "LICENSE_GRANTED",
        "license": data.model_dump()
    }


@app.post("/admin/license/revoke")
def revoke_license(data: LicenseRevoke, x_api_key: Optional[str] = Header(default=None)):
    require_admin_key(x_api_key)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE licenses
        SET status = 'REVOKED',
            revoked_at = ?
        WHERE product_id = ?
          AND universe_id = ?
          AND status = 'ACTIVE'
    """, (
        now_iso(),
        data.product_id,
        data.universe_id
    ))

    changed = cur.rowcount

    conn.commit()
    conn.close()

    if changed <= 0:
        return {
            "ok": False,
            "message": "NO_ACTIVE_LICENSE_FOUND"
        }

    return {
        "ok": True,
        "message": "LICENSE_REVOKED"
    }


@app.get("/admin/license/list")
def list_licenses(x_api_key: Optional[str] = Header(default=None)):
    require_admin_key(x_api_key)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            product_id,
            roblox_user_id,
            creator_type,
            creator_id,
            universe_id,
            status,
            created_at,
            revoked_at
        FROM licenses
        ORDER BY id DESC
        LIMIT 50
    """)

    rows = cur.fetchall()
    conn.close()

    licenses = []

    for row in rows:
        licenses.append({
            "id": row[0],
            "product_id": row[1],
            "roblox_user_id": row[2],
            "creator_type": row[3],
            "creator_id": row[4],
            "universe_id": row[5],
            "status": row[6],
            "created_at": row[7],
            "revoked_at": row[8],
        })

    return {
        "ok": True,
        "licenses": licenses
    }