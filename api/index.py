import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None

app = FastAPI(title="Vietnam Fuel Price Calculator", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

SOURCE_LIST = "https://moit.gov.vn/tin-tuc/thong-bao"
SOURCE_NAME = "Bộ Công Thương"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; VietnamFuelCalculator/3.0; +https://vercel.com)"
}
REQUEST_TIMEOUT = 20


def db():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    if psycopg is None:
        raise RuntimeError("psycopg is not installed")
    return psycopg.connect(url, row_factory=dict_row)


def init_db():
    with db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS fuel_prices (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            price_vnd INTEGER NOT NULL CHECK (price_vnd > 0),
            effective_at TIMESTAMPTZ NOT NULL,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE(code, effective_at)
        )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_fuel_prices_code_effective ON fuel_prices(code, effective_at DESC)")
        con.commit()


def parse_vnd(text: str) -> int:
    cleaned = text.replace(".", "").replace(",", "").replace(" ", "")
    value = int(cleaned)
    if value < 1_000 or value > 100_000:
        raise ValueError(f"Suspicious fuel price: {value}")
    return value


def extract_price(text: str, label: str) -> int:
    # The price must follow the label directly ("Xăng E10RON95-III: không cao hơn 19.845 đồng/lít").
    # [^\d]{0,80}? forbids digits between label and price, so a label mentioned earlier in the page
    # can never "borrow" the price of another fuel type further down.
    pattern = (
        rf"{re.escape(label)}[^\d]{{0,80}}?"
        rf"(\d{{1,3}}(?:[.,]\d{{3}})+)\s*(?:đồng\s*/\s*lít|đ\s*/\s*lít)"
    )
    for m in re.finditer(pattern, text, re.I):
        try:
            return parse_vnd(m.group(1))
        except ValueError:
            continue
    raise ValueError(f"Cannot extract {label}")


_DATE = r"ngày\s*(\d{1,2})\s*(?:tháng\s*|[./-])(\d{1,2})\s*(?:năm\s*|[./-])(\d{4})"
_TIME = r"(\d{1,2})\s*(?:giờ|h|g)\s*(\d{1,2})?\s*['’‘′`´]*"


def _iso(y: int, mo: int, d: int, hh: int, mm: int) -> str:
    datetime(y, mo, d, hh, mm)  # validate
    return f"{y:04d}-{mo:02d}-{d:02d}T{hh:02d}:{mm:02d}:00+07:00"


def parse_effective_at(text: str, title: str) -> str:
    """Effective time of the announcement, e.g. "15 giờ 00’ ngày 12 tháng 11 năm 2026".

    A page mentions several timestamps (previous period, tax measures, ...), so taking the first
    match is unreliable. Collect every "<hour> ngày <date>" and choose:
      1. the one on the same day/month as the title ("... ngày 12/11"), else
      2. the latest one (the new period is always newer than the periods it refers to).
    """
    found = []
    for m in re.finditer(rf"{_TIME}\s*{_DATE}", text, re.I):
        try:
            hh, mm, d, mo, y = int(m.group(1)), int(m.group(2) or 0), int(m.group(3)), int(m.group(4)), int(m.group(5))
            found.append((datetime(y, mo, d, hh, mm), d, mo))
        except ValueError:
            continue

    tm = re.search(r"ngày\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?:\s*[./-]\s*(\d{4}))?", title, re.I)
    title_dm = (int(tm.group(1)), int(tm.group(2))) if tm else None

    if found:
        same_day = [f for f in found if title_dm and (f[1], f[2]) == title_dm]
        chosen = max(same_day or found, key=lambda f: f[0])[0]
        return _iso(chosen.year, chosen.month, chosen.day, chosen.hour, chosen.minute)

    # Fallback: date in the title (year optional), default time 15:00.
    if tm:
        d, mo = int(tm.group(1)), int(tm.group(2))
        if tm.group(3):
            y = int(tm.group(3))
        else:
            years = re.findall(r"năm\s*(20\d{2})", text)
            y = int(max(set(years), key=years.count)) if years else datetime.now(timezone(timedelta(hours=7))).year
        try:
            return _iso(y, mo, d, 15, 0)
        except ValueError:
            pass

    raise ValueError("Cannot determine effective date")


def discover_latest_announcement():
    """All fuel-price announcements on the MOIT listing, newest first (by the date in the title)."""
    r = requests.get(SOURCE_LIST, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    import unicodedata

    def _plain(text):
        t = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
        return "".join(c for c in t if unicodedata.category(c) != "Mn")

    candidates = []
    seen = set()
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ", strip=True).split())
        href = urljoin(SOURCE_LIST, a["href"])
        plain = _plain(title)
        if re.search(r"dieu\s*han\w*\s*gia\s*(?:ban\s*)?xang\s*dau", plain) and href not in seen:
            seen.add(href)
            candidates.append((title, href))

    if not candidates:
        raise ValueError("No recent fuel-price announcement found on MOIT listing")

    def title_key(item):
        m = re.search(r"ngay\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?:\s*[./-]\s*(\d{4}))?", _plain(item[0]))
        if not m:
            return (0, 0, 0)
        year = int(m.group(3) or datetime.now(timezone(timedelta(hours=7))).year)
        return (year, int(m.group(2)), int(m.group(1)))

    return sorted(candidates, key=title_key, reverse=True)[0]  # newest first -> (title, url)


def collect_prices():
    title, source_url = discover_latest_announcement()
    r = requests.get(source_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())

    # MOIT has used both RON95-III and E10RON95-III wording in 2026.
    e5 = extract_price(text, "Xăng E5RON92")
    e10 = extract_price(text, "Xăng E10RON95-III")
    if e5 == e10:
        raise ValueError(f"E5 and E10 prices are identical ({e5}); refusing to save")
    effective = parse_effective_at(text, title)

    now = datetime.now(timezone.utc).isoformat()
    values = {
        "E5_RON92": ("E5 RON92", e5),
        "E10_RON95_III": ("E10 RON95-III", e10),
    }

    with db() as con:
        for code, (name, price) in values.items():
            con.execute("""
                INSERT INTO fuel_prices
                    (code, name, price_vnd, effective_at, source_name, source_url, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (code, effective_at) DO UPDATE SET
                    price_vnd = EXCLUDED.price_vnd,
                    source_name = EXCLUDED.source_name,
                    source_url = EXCLUDED.source_url,
                    updated_at = EXCLUDED.updated_at
            """, (code, name, price, effective, SOURCE_NAME, source_url, now))
        con.commit()

    return {
        "announcement_title": title,
        "source_url": source_url,
        "effective_at": effective,
        "checked_at": now,
        "prices": [
            {"code": code, "name": name, "price_vnd": price}
            for code, (name, price) in values.items()
        ],
    }


def latest_rows():
    with db() as con:
        return con.execute("""
            SELECT DISTINCT ON (code)
                code, name, price_vnd, effective_at, source_name, source_url, updated_at
            FROM fuel_prices
            ORDER BY code, effective_at DESC, id DESC
        """).fetchall()


def get_last_checked():
    with db() as con:
        row = con.execute("SELECT MAX(updated_at) AS last_checked FROM fuel_prices").fetchone()
        return row["last_checked"] if row else None


VN_TZ = timezone(timedelta(hours=7))


def should_refresh(now: datetime | None = None) -> bool:
    """Decide whether a user request should trigger a MOIT check.

    - Normally: re-check when data is older than 6 hours (catches ad-hoc announcements).
    - Thursday, from 15:00 Vietnam time (the regular adjustment slot): if no price with an
      effective time at/after today's 15:00 is stored yet, re-check every 10 minutes.
    """
    now = now or datetime.now(timezone.utc)
    with db() as con:
        row = con.execute(
            "SELECT MAX(updated_at) AS last_checked, MAX(effective_at) AS latest_effective FROM fuel_prices"
        ).fetchone()
    last = row["last_checked"] if row else None
    if last is None:
        return True
    if isinstance(last, str):
        last = datetime.fromisoformat(last.replace("Z", "+00:00"))
    age = (now - last).total_seconds()

    local = now.astimezone(VN_TZ)
    if local.weekday() == 3:  # Thursday
        slot = local.replace(hour=15, minute=0, second=0, microsecond=0)
        if local >= slot:
            latest = row["latest_effective"]
            if isinstance(latest, str):
                latest = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            if latest is None or latest < slot:
                return age >= 10 * 60
    return age >= 6 * 3600


def check_cron_secret(authorization: str | None, x_cron_secret: str | None):
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="CRON_SECRET is not configured")
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    supplied = bearer or x_cron_secret
    if supplied != secret:
        raise HTTPException(status_code=401, detail="Invalid cron secret")


@app.get("/")
def root():
    return {"name": "Vietnam Fuel Price Calculator", "status": "ok"}


@app.get("/api/health")
def health():
    try:
        init_db()
        return {"status": "ok", "database": "connected", "last_checked": get_last_checked()}
    except Exception as e:
        return {"status": "degraded", "database": "unavailable", "error": str(e)}


@app.get("/api/prices")
def prices(refresh: bool = Query(False)):
    init_db()
    refresh_attempted = False
    refresh_error = None

    # A user request can recover a stale database between scheduled cron runs.
    # A manual refresh (button) is honoured at most once every 30 seconds so it cannot hammer MOIT.
    manual = False
    if refresh:
        last = get_last_checked()
        if isinstance(last, str):
            last = datetime.fromisoformat(last.replace("Z", "+00:00"))
        manual = last is None or (datetime.now(timezone.utc) - last).total_seconds() >= 30
    if manual or should_refresh():
        refresh_attempted = True
        try:
            collect_prices()
        except Exception as e:
            refresh_error = str(e)

    rows = latest_rows()
    if not rows:
        if refresh_error:
            raise HTTPException(status_code=503, detail=f"No price data available: {refresh_error}")
        raise HTTPException(status_code=503, detail="No price data available")

    return {
        "prices": rows,
        "refresh_attempted": refresh_attempted,
        "refresh_error": refresh_error,
        "last_checked": get_last_checked(),
    }


@app.get("/api/prices/{code}")
def price(code: str):
    init_db()
    with db() as con:
        row = con.execute("""
            SELECT code,name,price_vnd,effective_at,source_name,source_url,updated_at
            FROM fuel_prices
            WHERE code=%s
            ORDER BY effective_at DESC, id DESC
            LIMIT 1
        """, (code,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Fuel type not found")
    return dict(row)


@app.get("/api/history")
def history(limit: int = Query(20, ge=1, le=100)):
    init_db()
    with db() as con:
        rows = con.execute("""
            SELECT code,name,price_vnd,effective_at,source_name,source_url,updated_at
            FROM fuel_prices
            ORDER BY effective_at DESC, code ASC
            LIMIT %s
        """, (limit,)).fetchall()
    return {"history": rows}


def _update_prices(
    authorization: str | None,
    x_cron_secret: str | None,
):
    check_cron_secret(authorization, x_cron_secret)
    try:
        init_db()
        result = collect_prices()
        return {"status": "updated", **result}
    except Exception as e:
        # Never overwrite known-good data when scraping fails.
        raise HTTPException(status_code=502, detail=f"Price update failed: {e}")


@app.get("/api/cron/update-prices")
def cron_update_prices_get(
    authorization: str | None = Header(default=None),
    x_cron_secret: str | None = Header(default=None),
):
    # Vercel Cron invokes the configured path with HTTP GET.
    return _update_prices(authorization, x_cron_secret)


@app.post("/api/cron/update-prices")
def cron_update_prices_post(
    authorization: str | None = Header(default=None),
    x_cron_secret: str | None = Header(default=None),
):
    # POST remains available for manual testing.
    return _update_prices(authorization, x_cron_secret)
