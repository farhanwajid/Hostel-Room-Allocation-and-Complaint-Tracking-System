"""Hostel Management API.

All routes live here and use plain SQL so the MySQL schema in database/schema.sql
stays the single source of truth. Role rules:
  administrator     - manages everything
  resident          - sees/pays own fees, files + tracks own complaints
  maintenance_staff - works on complaints (self-assign, start, resolve)
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import engine, get_db

logger = logging.getLogger("hostel")
settings = get_settings()
password_hasher = PasswordHasher()
DEFAULT_FEE_AMOUNT = 420  # used only when a resident has no allocation yet
CENT = Decimal("0.01")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def ensure_pricing_columns() -> None:
    """Adds price columns to databases created from an older schema.sql."""
    with engine.begin() as connection:
        for table in ("rooms", "beds", "allocations"):
            try:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN monthly_amount DECIMAL(12,2) NOT NULL DEFAULT 0"))
            except SQLAlchemyError:
                continue  # column already exists


def log_activity(db: Session, user_id: int | None, action: str, entity_type: str,
                 entity_id: int | None = None, details: dict | None = None) -> None:
    db.execute(
        text("INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details) "
             "VALUES (:u, :a, :t, :e, :d)"),
        {"u": user_id, "a": action, "t": entity_type, "e": entity_id,
         "d": json.dumps(details, default=str) if details else None},
    )


def notify(db: Session, user_id: int | None, title: str, message: str) -> None:
    if not user_id:
        return
    db.execute(
        text("INSERT INTO notifications (user_id, title, message) VALUES (:u, :t, :m)"),
        {"u": user_id, "t": title, "m": message[:500]},
    )


def ensure_current_invoices(db: Session, resident_id: int | None = None) -> int:
    """Creates this month's invoice for active residents that do not have one.

    The amount is the resident's allocated bed price (or the default if unallocated).
    Returns the number of invoices created. Safe to call repeatedly.
    """
    params: dict = {"period": date.today().strftime("%B %Y"), "amount": DEFAULT_FEE_AMOUNT,
                    "due_date": date.today().replace(day=5)}
    extra = ""
    if resident_id is not None:
        extra = " AND r.id=:resident_id"
        params["resident_id"] = resident_id
    count_sql = "SELECT COUNT(*) FROM fee_invoices WHERE fee_period=:period"
    before = db.execute(text(count_sql), {"period": params["period"]}).scalar_one()
    db.execute(text(f"""
        INSERT INTO fee_invoices (resident_id, fee_period, amount_due, due_date, status)
        SELECT r.id, :period, COALESCE(NULLIF(a.monthly_amount, 0), :amount), :due_date, 'unpaid'
        FROM residents r
        LEFT JOIN allocations a ON a.resident_id = r.id AND a.status = 'active'
        WHERE r.is_active = 1{extra}
        ON DUPLICATE KEY UPDATE fee_invoices.resident_id = fee_invoices.resident_id
    """), params)
    after = db.execute(text(count_sql), {"period": params["period"]}).scalar_one()
    return int(after - before)


def sync_current_invoice(db: Session, resident_id: int, amount) -> None:
    """After a (re)allocation, re-price this month's invoice if nothing was paid yet."""
    if Decimal(str(amount or 0)) <= 0:
        return
    db.execute(
        text("UPDATE fee_invoices SET amount_due=:amount "
             "WHERE resident_id=:rid AND status='unpaid' AND fee_period=:period"),
        {"amount": amount, "rid": resident_id, "period": date.today().strftime("%B %Y")},
    )


def academic_end_date(start_date: date, academic_year: int) -> date:
    years_remaining = max(1, 5 - academic_year)
    try:
        return start_date.replace(year=start_date.year + years_remaining)
    except ValueError:  # 29 Feb
        return start_date.replace(month=2, day=28, year=start_date.year + years_remaining)


def assign_bed(db: Session, resident: dict, bed: dict, admin_id: int, start: date) -> tuple[int, date]:
    """Creates an active allocation, re-prices the invoice, logs and notifies."""
    end = academic_end_date(start, resident["academic_year"])
    row = db.execute(text("""
        INSERT INTO allocations (resident_id, bed_id, allocated_by, start_date, end_date, monthly_amount, status)
        VALUES (:rid, :bid, :admin, :start, :end, :amount, 'active')
    """), {"rid": resident["id"], "bid": bed["id"], "admin": admin_id, "start": start, "end": end,
           "amount": bed["monthly_amount"]})
    sync_current_invoice(db, resident["id"], bed["monthly_amount"])
    label = bed.get("label") or f"bed {bed['id']}"
    log_activity(db, admin_id, "allocation.created", "allocation", row.lastrowid,
                 {"resident_id": resident["id"], "bed": label})
    notify(db, resident.get("user_id"), "Bed allocated", f"You have been allocated {label}.")
    return row.lastrowid, end


BED_SELECT = """
    SELECT b.id, b.status, b.monthly_amount,
           CONCAT(h.name, ' / Room ', r.room_number, ' / Bed ', b.bed_number) AS label
    FROM beds b JOIN rooms r ON r.id=b.room_id JOIN hostels h ON h.id=r.hostel_id
"""


def auto_assign_unallocated(db: Session, admin_id: int) -> dict:
    residents = db.execute(text("""
        SELECT r.id, r.user_id, r.academic_year
        FROM residents r
        LEFT JOIN allocations a ON a.resident_id=r.id AND a.status='active'
        WHERE r.is_active=1 AND r.eligibility_status='eligible' AND a.id IS NULL
        ORDER BY r.id
    """)).mappings().all()
    assigned = 0
    for resident in residents:
        bed = db.execute(text(BED_SELECT + """
            WHERE b.status='available'
              AND NOT EXISTS (SELECT 1 FROM allocations a WHERE a.bed_id=b.id AND a.status='active')
            ORDER BY b.id LIMIT 1 FOR UPDATE OF b
        """)).mappings().one_or_none()
        if not bed:
            break
        assign_bed(db, dict(resident), dict(bed), admin_id, date.today())
        assigned += 1
    return {"assigned": assigned, "waiting": len(residents) - assigned}


# --------------------------------------------------------------------------- #
# App + auth
# --------------------------------------------------------------------------- #
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
app = FastAPI(title=settings.app_name, version="0.2.0",
              description="REST API for hostel allocations, complaints, and fee management.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup() -> None:
    try:
        ensure_pricing_columns()
    except SQLAlchemyError:
        logger.warning("Database not reachable at startup; continuing.")


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@app.get("/health/database", tags=["system"])
def database_health_check() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database health check failed") from exc
    return {"status": "ok"}


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    email: str
    role: str
    resident_id: int | None = None


class LoginJson(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    roll_number: str = Field(min_length=1, max_length=40)
    course: str = Field(min_length=1, max_length=120)
    academic_year: int = Field(ge=1, le=8)
    phone: str | None = Field(default=None, max_length=30)


class DashboardStats(BaseModel):
    residents: int = 0
    rooms: int = 0
    beds: int = 0
    occupied_beds: int = 0
    available_beds: int = 0
    occupancy_percent: float = 0
    open_complaints: int = 0
    urgent_complaints: int = 0
    outstanding_balance: float = 0
    collected_this_month: float = 0
    total_residents: int = 0
    resolved_complaints: int = 0
    in_progress_complaints: int = 0


def create_token(user_id: int, role: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_token_minutes)
    return jwt.encode({"sub": str(user_id), "role": role, "exp": expires}, settings.jwt_secret_key, algorithm="HS256")


def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> dict:
    credentials_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise credentials_error from exc
    user = db.execute(
        text("SELECT u.id, u.full_name, u.email, u.role, u.is_active, r.id AS resident_id "
             "FROM users u LEFT JOIN residents r ON r.user_id = u.id AND r.is_active = 1 WHERE u.id = :id"),
        {"id": user_id},
    ).mappings().one_or_none()
    if not user or not user["is_active"]:
        raise credentials_error
    return dict(user)


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "administrator":
        raise HTTPException(status_code=403, detail="Administrator permission required")
    return user


def staff_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] not in {"administrator", "maintenance_staff"}:
        raise HTTPException(status_code=403, detail="Maintenance permission required")
    return user


def authenticate_user(email: str, password: str, db: Session) -> dict:
    try:
        user = db.execute(
            text("SELECT u.id, u.full_name, u.email, u.password_hash, u.role, u.is_active, r.id AS resident_id "
                 "FROM users u LEFT JOIN residents r ON r.user_id=u.id AND r.is_active=1 WHERE u.email = :email"),
            {"email": email},
        ).mappings().one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Authentication service is unavailable") from exc
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    try:
        password_hasher.verify(user["password_hash"], password)
    except (InvalidHashError, VerificationError, VerifyMismatchError) as exc:
        raise HTTPException(status_code=401, detail="Invalid email or password") from exc
    return dict(user)


def check_password(db: Session, user_id: int, password: str) -> bool:
    stored = db.execute(text("SELECT password_hash FROM users WHERE id=:id"), {"id": user_id}).scalar_one_or_none()
    if not stored:
        return False
    try:
        password_hasher.verify(stored, password)
        return True
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def token_response(user: dict) -> dict:
    return {"access_token": create_token(user["id"], user["role"]), "token_type": "bearer",
            "user": UserOut(**{k: user.get(k) for k in ("id", "full_name", "email", "role", "resident_id")})}


@app.post("/api/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> dict:
    return token_response(authenticate_user(form.username, form.password, db))


@app.post("/auth/login")
def login_json(payload: LoginJson, db: Session = Depends(get_db)) -> dict:
    return token_response(authenticate_user(payload.email, payload.password, db))


@app.post("/api/auth/register", status_code=201)
@app.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    """Self-registration. Residents are 'eligible' straight away so an admin can allocate them
    (an admin can still mark someone ineligible from the Residents page)."""
    try:
        existing = db.execute(
            text("SELECT id FROM users WHERE email=:email UNION SELECT id FROM residents WHERE email=:email "
                 "UNION SELECT id FROM residents WHERE roll_number=:roll"),
            {"email": payload.email, "roll": payload.roll_number},
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="An account with this email or roll number already exists")
        user_result = db.execute(
            text("INSERT INTO users (full_name, email, password_hash, role) "
                 "VALUES (:full_name, :email, :password_hash, 'resident')"),
            {"full_name": payload.full_name, "email": payload.email,
             "password_hash": password_hasher.hash(payload.password)},
        )
        resident_result = db.execute(
            text("INSERT INTO residents (user_id, roll_number, full_name, email, phone, course, academic_year, eligibility_status) "
                 "VALUES (:user_id, :roll_number, :full_name, :email, :phone, :course, :academic_year, 'eligible')"),
            {"user_id": user_result.lastrowid, **payload.model_dump(exclude={"password"})},
        )
        ensure_current_invoices(db, resident_result.lastrowid)
        log_activity(db, user_result.lastrowid, "resident.registered", "resident", resident_result.lastrowid)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account could not be created; check unique details") from exc
    user = db.execute(
        text("SELECT u.id, u.full_name, u.email, u.role, r.id AS resident_id "
             "FROM users u LEFT JOIN residents r ON r.user_id=u.id WHERE u.id=:id"),
        {"id": user_result.lastrowid},
    ).mappings().one()
    return token_response(dict(user))


@app.get("/api/auth/me", response_model=UserOut)
def me(user: dict = Depends(current_user)) -> dict:
    return user


# --------------------------------------------------------------------------- #
# Dashboards (one per role)
# --------------------------------------------------------------------------- #
@app.get("/api/dashboard/stats", response_model=DashboardStats)
def dashboard_stats(_: dict = Depends(admin_user), db: Session = Depends(get_db)) -> DashboardStats:
    """Hostel-wide numbers. Administrator only."""
    try:
        row = db.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM residents WHERE is_active = 1) residents,
              (SELECT COUNT(*) FROM rooms WHERE is_active = 1) rooms,
              (SELECT COUNT(*) FROM beds WHERE status <> 'retired') beds,
              (SELECT COUNT(*) FROM allocations WHERE status = 'active') occupied_beds,
              (SELECT COUNT(*) FROM beds b WHERE b.status = 'available'
                  AND NOT EXISTS (SELECT 1 FROM allocations a WHERE a.bed_id=b.id AND a.status='active')) available_beds,
              (SELECT COUNT(*) FROM complaints WHERE status NOT IN ('resolved', 'closed')) open_complaints,
              (SELECT COUNT(*) FROM complaints WHERE priority = 'urgent' AND status NOT IN ('resolved', 'closed')) urgent_complaints,
              (SELECT COUNT(*) FROM complaints WHERE status IN ('resolved', 'closed')) resolved_complaints,
              (SELECT COUNT(*) FROM complaints WHERE status IN ('assigned', 'in_progress')) in_progress_complaints,
              (SELECT COALESCE(SUM(i.amount_due - COALESCE(p.paid, 0)), 0)
                 FROM fee_invoices i
                 JOIN residents rs ON rs.id = i.resident_id AND rs.is_active = 1
                 LEFT JOIN (SELECT invoice_id, SUM(amount) paid FROM payments GROUP BY invoice_id) p
                   ON p.invoice_id = i.id
                WHERE i.status <> 'cancelled') outstanding_balance,
              (SELECT COALESCE(SUM(amount), 0) FROM payments
                WHERE YEAR(paid_at) = YEAR(CURDATE()) AND MONTH(paid_at) = MONTH(CURDATE())) collected_this_month,
              (SELECT COUNT(*) FROM residents WHERE is_active = 1) total_residents
        """)).mappings().one()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Dashboard data is unavailable") from exc
    total = int(row["beds"] or 0)
    occupied = int(row["occupied_beds"] or 0)
    return DashboardStats(**row, occupancy_percent=round(occupied / total * 100, 1) if total else 0)


@app.get("/api/dashboard/activity")
def dashboard_activity(_: dict = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT type, title, description, occurred_at FROM (
          SELECT 'Allocation' AS type, CONCAT('Allocation for ', r.full_name) AS title,
                 CONCAT('Room ', rm.room_number, ', Bed ', b.bed_number) AS description,
                 a.created_at AS occurred_at
          FROM allocations a JOIN residents r ON r.id=a.resident_id
          JOIN beds b ON b.id=a.bed_id JOIN rooms rm ON rm.id=b.room_id
          UNION ALL
          SELECT 'Complaint', CONCAT('Complaint: ', subject), status, submitted_at FROM complaints
          UNION ALL
          SELECT 'Payment', CONCAT('Payment received from ', r.full_name), CONCAT('₹', p.amount), p.paid_at
          FROM payments p JOIN fee_invoices i ON i.id=p.invoice_id JOIN residents r ON r.id=i.resident_id
        ) feed ORDER BY occurred_at DESC LIMIT 6
    """)).mappings().all()]


@app.get("/api/dashboard/me")
def dashboard_me(user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Personal dashboard for residents and maintenance staff."""
    role = user["role"]
    if role == "resident":
        rid = user.get("resident_id")
        allocation = db.execute(text("""
            SELECT h.name AS hostel, r.room_number, b.bed_number, a.start_date, a.end_date, a.monthly_amount
            FROM allocations a JOIN beds b ON b.id=a.bed_id JOIN rooms r ON r.id=b.room_id
            JOIN hostels h ON h.id=r.hostel_id
            WHERE a.resident_id=:rid AND a.status='active'
        """), {"rid": rid}).mappings().one_or_none()
        outstanding = db.execute(text("""
            SELECT COALESCE(SUM(i.amount_due - COALESCE(p.paid, 0)), 0)
            FROM fee_invoices i
            LEFT JOIN (SELECT invoice_id, SUM(amount) paid FROM payments GROUP BY invoice_id) p ON p.invoice_id=i.id
            WHERE i.resident_id=:rid AND i.status <> 'cancelled'
        """), {"rid": rid}).scalar_one()
        counts = db.execute(text("""
            SELECT COALESCE(SUM(status NOT IN ('resolved','closed')), 0) AS open_count,
                   COALESCE(SUM(status IN ('resolved','closed')), 0) AS resolved_count
            FROM complaints WHERE resident_id=:rid
        """), {"rid": rid}).mappings().one()
        recent = db.execute(text("""
            SELECT id, subject, category, priority, status, submitted_at
            FROM complaints WHERE resident_id=:rid ORDER BY submitted_at DESC LIMIT 5
        """), {"rid": rid}).mappings().all()
        return {"role": role, "allocation": dict(allocation) if allocation else None,
                "outstanding_balance": float(outstanding), "open_complaints": int(counts["open_count"]),
                "resolved_complaints": int(counts["resolved_count"]), "recent_complaints": [dict(r) for r in recent]}
    if role == "maintenance_staff":
        uid = user["id"]
        counts = db.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM complaints WHERE assigned_to=:uid AND status='assigned') AS assigned_to_me,
              (SELECT COUNT(*) FROM complaints WHERE assigned_to=:uid AND status='in_progress') AS in_progress,
              (SELECT COUNT(*) FROM complaints WHERE status='open') AS unassigned_open,
              (SELECT COUNT(*) FROM complaints WHERE assigned_to=:uid AND status IN ('resolved','closed')) AS resolved_by_me
        """), {"uid": uid}).mappings().one()
        queue = db.execute(text("""
            SELECT c.id, c.subject, c.category, c.priority, c.status, r.full_name AS resident_name
            FROM complaints c JOIN residents r ON r.id=c.resident_id
            WHERE (c.assigned_to=:uid AND c.status IN ('assigned','in_progress')) OR c.status='open'
            ORDER BY FIELD(c.priority,'urgent','high','medium','low'), c.submitted_at LIMIT 8
        """), {"uid": uid}).mappings().all()
        return {"role": role, **{k: int(v) for k, v in counts.items()}, "queue": [dict(q) for q in queue]}
    return {"role": role}


# --------------------------------------------------------------------------- #
# Schemas for write endpoints
# --------------------------------------------------------------------------- #
class ResidentCreate(BaseModel):
    roll_number: str = Field(min_length=1, max_length=40)
    full_name: str = Field(min_length=1, max_length=120)
    email: str
    course: str
    academic_year: int = Field(ge=1, le=8)
    phone: str | None = None


class EligibilityUpdate(BaseModel):
    eligibility_status: str


class AllocationCreate(BaseModel):
    resident_id: int
    bed_id: int
    start_date: str


class TransferCreate(BaseModel):
    destination_bed_id: int
    reason: str = Field(min_length=1, max_length=500)


class ComplaintCreate(BaseModel):
    resident_id: int
    room_id: int | None = None
    bed_id: int | None = None
    category: str
    subject: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1)
    priority: str = "medium"


class ComplaintUpdate(BaseModel):
    status: str
    remark: str | None = None
    assigned_to: int | None = None


class InvoiceCreate(BaseModel):
    resident_id: int
    fee_period: str
    amount_due: Decimal = Field(gt=0)
    due_date: str


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    payment_reference: str | None = Field(default=None, max_length=80)
    transaction_password: str = Field(min_length=1, max_length=128)


class HostelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=255)
    description: str | None = None


class RoomCreate(BaseModel):
    hostel_id: int
    room_number: str = Field(min_length=1, max_length=20)
    floor: int
    room_type: str = "double"
    monthly_amount: Decimal = Field(ge=0)
    bed_number: str | None = None
    bed_amount: Decimal | None = Field(default=None, ge=0)
    bed_count: int = Field(default=1, ge=1, le=100)


class BedCreate(BaseModel):
    room_id: int
    bed_number: str = Field(min_length=1, max_length=20)
    status: str = "available"
    monthly_amount: Decimal = Field(ge=0)


# --------------------------------------------------------------------------- #
# Hostels, rooms, beds (admin only)
# --------------------------------------------------------------------------- #
@app.get("/api/hostels")
def hostels(_: dict = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT h.id, h.name, h.location, h.description, COUNT(DISTINCT r.id) rooms,
               COUNT(b.id) beds, COALESCE(SUM(b.status = 'available'), 0) available_beds
        FROM hostels h LEFT JOIN rooms r ON r.hostel_id=h.id AND r.is_active=1
        LEFT JOIN beds b ON b.room_id=r.id
        WHERE h.is_active=1 GROUP BY h.id ORDER BY h.name
    """)).mappings().all()]


@app.post("/api/hostels", status_code=201)
def create_hostel(payload: HostelCreate, _: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        result = db.execute(text("INSERT INTO hostels (name, location, description) VALUES (:name, :location, :description)"),
                            payload.model_dump())
        db.commit()
        return {"id": result.lastrowid, **payload.model_dump()}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Hostel name already exists") from exc


@app.get("/api/rooms")
def rooms(_: dict = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT r.id, r.room_number, r.floor, r.room_type, r.monthly_amount, h.name AS hostel,
               COUNT(b.id) beds, COALESCE(SUM(b.status='available' AND a.id IS NULL), 0) available_beds,
               COUNT(a.id) occupied_beds
        FROM rooms r JOIN hostels h ON h.id=r.hostel_id
        LEFT JOIN beds b ON b.room_id=r.id
        LEFT JOIN allocations a ON a.bed_id=b.id AND a.status='active'
        WHERE r.is_active=1 GROUP BY r.id, h.name ORDER BY h.name, r.room_number
    """)).mappings().all()]


@app.post("/api/rooms", status_code=201)
def create_room(payload: RoomCreate, _: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        result = db.execute(
            text("INSERT INTO rooms (hostel_id, room_number, floor, room_type, monthly_amount) "
                 "VALUES (:hostel_id, :room_number, :floor, :room_type, :monthly_amount)"),
            payload.model_dump(include={"hostel_id", "room_number", "floor", "room_type", "monthly_amount"}))
        if payload.bed_number:
            first_bed = payload.bed_number.strip()
            for offset in range(payload.bed_count):
                if first_bed.isdigit():
                    bed_number = str(int(first_bed) + offset)
                elif len(first_bed) == 1 and first_bed.isalpha():
                    bed_number = chr(ord(first_bed.upper()) + offset)
                else:
                    bed_number = first_bed if offset == 0 else f"{first_bed}-{offset + 1}"
                amount = payload.bed_amount if payload.bed_amount is not None else payload.monthly_amount
                db.execute(text("INSERT INTO beds (room_id, bed_number, status, monthly_amount) "
                                "VALUES (:room_id, :bed_number, 'available', :amount)"),
                           {"room_id": result.lastrowid, "bed_number": bed_number, "amount": amount})
        db.commit()
        return {"id": result.lastrowid, **payload.model_dump(mode="json")}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Room could not be created (room number may already exist in this hostel)") from exc


@app.delete("/api/rooms/{room_id}")
def delete_room(room_id: int, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        occupied = db.execute(text("""
            SELECT COUNT(*) FROM allocations a JOIN beds b ON b.id=a.bed_id
            WHERE b.room_id=:id AND a.status='active'"""), {"id": room_id}).scalar_one()
        if occupied:
            raise HTTPException(status_code=409, detail="Room has active allocations. Cancel or transfer them first.")
        db.execute(text("DELETE FROM room_transfers WHERE from_allocation_id IN (SELECT a.id FROM allocations a JOIN beds b ON b.id=a.bed_id WHERE b.room_id=:id) "
                        "OR to_allocation_id IN (SELECT a.id FROM allocations a JOIN beds b ON b.id=a.bed_id WHERE b.room_id=:id)"), {"id": room_id})
        db.execute(text("DELETE FROM complaint_updates WHERE complaint_id IN (SELECT id FROM complaints WHERE room_id=:id)"), {"id": room_id})
        db.execute(text("DELETE FROM complaints WHERE room_id=:id"), {"id": room_id})
        db.execute(text("DELETE FROM allocations WHERE bed_id IN (SELECT id FROM beds WHERE room_id=:id)"), {"id": room_id})
        db.execute(text("DELETE FROM beds WHERE room_id=:id"), {"id": room_id})
        result = db.execute(text("DELETE FROM rooms WHERE id=:id"), {"id": room_id})
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="Room not found")
        log_activity(db, user["id"], "room.deleted", "room", room_id)
        db.commit()
        return {"id": room_id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Room could not be removed") from exc


@app.get("/api/beds")
def beds(_: dict = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT b.id, b.bed_number, b.status, b.monthly_amount, r.room_number, h.name AS hostel,
               a.resident_id, res.full_name AS resident_name,
               CASE WHEN b.status = 'available' AND a.id IS NULL THEN 1 ELSE 0 END AS available_for_allocation
        FROM beds b JOIN rooms r ON r.id=b.room_id JOIN hostels h ON h.id=r.hostel_id
        LEFT JOIN allocations a ON a.bed_id=b.id AND a.status='active'
        LEFT JOIN residents res ON res.id=a.resident_id
        ORDER BY h.name, r.room_number, b.bed_number
    """)).mappings().all()]


@app.post("/api/beds", status_code=201)
def create_bed(payload: BedCreate, _: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    if payload.status not in {"available", "maintenance", "retired"}:
        raise HTTPException(status_code=422, detail="Invalid bed status")
    try:
        result = db.execute(text("INSERT INTO beds (room_id, bed_number, status, monthly_amount) "
                                 "VALUES (:room_id, :bed_number, :status, :monthly_amount)"), payload.model_dump())
        db.commit()
        return {"id": result.lastrowid, **payload.model_dump(mode="json")}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bed number already exists in this room") from exc


# --------------------------------------------------------------------------- #
# Residents (admin only). Removal is a soft delete so history is retained.
# --------------------------------------------------------------------------- #
@app.get("/api/residents")
def residents(_: dict = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT r.id, r.roll_number, r.full_name, r.email, r.course, r.academic_year, r.eligibility_status,
               a.status AS allocation_status,
               CONCAT(h.name, ' / ', rm.room_number, ' / ', b.bed_number) AS allocation
        FROM residents r
        LEFT JOIN allocations a ON a.resident_id = r.id AND a.status = 'active'
        LEFT JOIN beds b ON b.id = a.bed_id
        LEFT JOIN rooms rm ON rm.id = b.room_id
        LEFT JOIN hostels h ON h.id = rm.hostel_id
        WHERE r.is_active = 1 ORDER BY r.full_name
    """)).mappings().all()]


@app.post("/api/residents", status_code=201)
def create_resident(payload: ResidentCreate, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        row = db.execute(text("""
            INSERT INTO residents (roll_number, full_name, email, phone, course, academic_year, eligibility_status)
            VALUES (:roll_number, :full_name, :email, :phone, :course, :academic_year, 'eligible')
        """), payload.model_dump())
        ensure_current_invoices(db, row.lastrowid)
        log_activity(db, user["id"], "resident.created", "resident", row.lastrowid)
        db.commit()
        return {"id": row.lastrowid, **payload.model_dump(), "eligibility_status": "eligible"}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Resident could not be created; check unique fields") from exc


@app.patch("/api/residents/{resident_id}/eligibility")
def set_eligibility(resident_id: int, payload: EligibilityUpdate, user: dict = Depends(admin_user),
                    db: Session = Depends(get_db)) -> dict:
    if payload.eligibility_status not in {"eligible", "ineligible", "pending"}:
        raise HTTPException(status_code=422, detail="Invalid eligibility status")
    row = db.execute(text("SELECT user_id FROM residents WHERE id=:id AND is_active=1"), {"id": resident_id}).mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Resident not found")
    db.execute(text("UPDATE residents SET eligibility_status=:s WHERE id=:id"), {"s": payload.eligibility_status, "id": resident_id})
    log_activity(db, user["id"], "resident.eligibility", "resident", resident_id, {"status": payload.eligibility_status})
    notify(db, row["user_id"], "Eligibility updated", f"Your hostel eligibility is now '{payload.eligibility_status}'.")
    db.commit()
    return {"id": resident_id, "eligibility_status": payload.eligibility_status}


@app.delete("/api/residents/{resident_id}")
def delete_resident(resident_id: int, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    """Soft delete: deactivates the resident (and login), cancels their bed, keeps invoices/payments."""
    try:
        resident = db.execute(text("SELECT id, user_id FROM residents WHERE id=:id AND is_active=1 FOR UPDATE"),
                              {"id": resident_id}).mappings().one_or_none()
        if not resident:
            raise HTTPException(status_code=404, detail="Resident not found")
        db.execute(text("UPDATE allocations SET status='cancelled', end_date=GREATEST(start_date, CURDATE()), "
                        "cancellation_reason='Resident removed' WHERE resident_id=:id AND status='active'"), {"id": resident_id})
        db.execute(text("UPDATE residents SET is_active=0 WHERE id=:id"), {"id": resident_id})
        if resident["user_id"]:
            db.execute(text("UPDATE users SET is_active=0 WHERE id=:id"), {"id": resident["user_id"]})
        log_activity(db, user["id"], "resident.deactivated", "resident", resident_id)
        db.commit()
        return {"id": resident_id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Resident could not be removed") from exc


# --------------------------------------------------------------------------- #
# Allocations
# --------------------------------------------------------------------------- #
@app.get("/api/allocations")
def allocations(user: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    if user["role"] == "maintenance_staff":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    rid = user.get("resident_id") if user["role"] == "resident" else None
    return [dict(row) for row in db.execute(text("""
        SELECT a.id, res.full_name AS resident_name, h.name AS hostel,
               r.room_number, b.bed_number, a.start_date, a.end_date, a.status, a.monthly_amount
        FROM allocations a JOIN residents res ON res.id=a.resident_id
        JOIN beds b ON b.id=a.bed_id JOIN rooms r ON r.id=b.room_id
        JOIN hostels h ON h.id=r.hostel_id
        WHERE (:rid IS NULL OR a.resident_id=:rid)
        ORDER BY a.start_date DESC, a.id DESC LIMIT 200
    """), {"rid": rid}).mappings().all()]


@app.post("/api/allocations/auto-assign")
def auto_assign(user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    """Explicit action (replaces the old hidden side effect on GET /allocations)."""
    try:
        result = auto_assign_unallocated(db, user["id"])
        db.commit()
        return result
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Auto-assign failed and was rolled back") from exc


@app.post("/api/allocations", status_code=201)
def allocate(payload: AllocationCreate, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        try:
            start = date.fromisoformat(payload.start_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid start date") from exc
        resident = db.execute(text("SELECT id, user_id, eligibility_status, academic_year FROM residents "
                                   "WHERE id=:id AND is_active=1 FOR UPDATE"), {"id": payload.resident_id}).mappings().one_or_none()
        bed = db.execute(text(BED_SELECT + " WHERE b.id=:id FOR UPDATE OF b"), {"id": payload.bed_id}).mappings().one_or_none()
        if not resident or resident["eligibility_status"] != "eligible":
            raise HTTPException(status_code=409, detail="Resident is not eligible for allocation")
        if not bed or bed["status"] != "available":
            raise HTTPException(status_code=409, detail="Bed is unavailable")
        if db.execute(text("SELECT id FROM allocations WHERE resident_id=:r AND status='active'"), {"r": payload.resident_id}).first():
            raise HTTPException(status_code=409, detail="Resident already has an active allocation")
        if db.execute(text("SELECT id FROM allocations WHERE bed_id=:b AND status='active'"), {"b": payload.bed_id}).first():
            raise HTTPException(status_code=409, detail="Bed is already occupied")
        allocation_id, end = assign_bed(db, dict(resident), dict(bed), user["id"], start)
        db.commit()
        return {"id": allocation_id, "resident_id": payload.resident_id, "bed_id": payload.bed_id,
                "start_date": start, "end_date": end, "monthly_amount": bed["monthly_amount"], "status": "active"}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Allocation failed due to a conflicting record") from exc


@app.delete("/api/allocations/{allocation_id}")
def cancel_allocation(allocation_id: int, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    """Cancels an active allocation (the row is kept as history)."""
    try:
        alloc = db.execute(text("SELECT a.id, r.user_id FROM allocations a JOIN residents r ON r.id=a.resident_id "
                                "WHERE a.id=:id AND a.status='active' FOR UPDATE"), {"id": allocation_id}).mappings().one_or_none()
        if not alloc:
            raise HTTPException(status_code=404, detail="Active allocation not found")
        db.execute(text("UPDATE allocations SET status='cancelled', end_date=GREATEST(start_date, CURDATE()), "
                        "cancellation_reason='Cancelled by administrator' WHERE id=:id"), {"id": allocation_id})
        log_activity(db, user["id"], "allocation.cancelled", "allocation", allocation_id)
        notify(db, alloc["user_id"], "Allocation cancelled", "Your bed allocation was cancelled by the administrator.")
        db.commit()
        return {"id": allocation_id, "cancelled": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Allocation could not be cancelled") from exc


@app.post("/api/allocations/{allocation_id}/transfer", status_code=201)
def transfer(allocation_id: int, payload: TransferCreate, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        alloc = db.execute(text("SELECT a.*, r.user_id FROM allocations a JOIN residents r ON r.id=a.resident_id "
                                "WHERE a.id=:id AND a.status='active' FOR UPDATE OF a"), {"id": allocation_id}).mappings().one_or_none()
        if not alloc:
            raise HTTPException(status_code=404, detail="Active allocation not found")
        bed = db.execute(text(BED_SELECT + " WHERE b.id=:id FOR UPDATE OF b"), {"id": payload.destination_bed_id}).mappings().one_or_none()
        if not bed or bed["status"] != "available":
            raise HTTPException(status_code=409, detail="Destination bed is unavailable")
        if bed["id"] == alloc["bed_id"]:
            raise HTTPException(status_code=409, detail="Resident is already in that bed")
        if db.execute(text("SELECT id FROM allocations WHERE bed_id=:b AND status='active'"), {"b": bed["id"]}).first():
            raise HTTPException(status_code=409, detail="Destination bed is already occupied")
        db.execute(text("UPDATE allocations SET status='completed', end_date=GREATEST(start_date, CURDATE()) WHERE id=:id"), {"id": allocation_id})
        new_alloc = db.execute(text("""
            INSERT INTO allocations (resident_id, bed_id, allocated_by, start_date, end_date, monthly_amount, status)
            VALUES (:rid, :bid, :admin, CURDATE(), :end, :amount, 'active')
        """), {"rid": alloc["resident_id"], "bid": bed["id"], "admin": user["id"],
               "end": alloc["end_date"], "amount": bed["monthly_amount"]})
        db.execute(text("INSERT INTO room_transfers (resident_id, from_allocation_id, to_allocation_id, reason, transferred_by) "
                        "VALUES (:rid, :f, :t, :reason, :admin)"),
                   {"rid": alloc["resident_id"], "f": allocation_id, "t": new_alloc.lastrowid,
                    "reason": payload.reason, "admin": user["id"]})
        sync_current_invoice(db, alloc["resident_id"], bed["monthly_amount"])
        log_activity(db, user["id"], "allocation.transferred", "allocation", new_alloc.lastrowid,
                     {"from": allocation_id, "to_bed": bed["label"]})
        notify(db, alloc["user_id"], "Room transfer", f"You have been moved to {bed['label']}.")
        db.commit()
        return {"from_allocation_id": allocation_id, "to_allocation_id": new_alloc.lastrowid, "status": "completed"}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Transfer failed and was rolled back") from exc


# --------------------------------------------------------------------------- #
# Complaints
# --------------------------------------------------------------------------- #
COMPLAINT_FLOW = {"open": {"assigned"}, "assigned": {"in_progress"}, "in_progress": {"resolved"},
                  "resolved": {"closed"}, "closed": set()}


@app.get("/api/staff")
def maintenance_staff(_: dict = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(r) for r in db.execute(text(
        "SELECT id, full_name FROM users WHERE role='maintenance_staff' AND is_active=1 ORDER BY full_name")).mappings().all()]


@app.get("/api/complaints")
def complaints(user: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Residents see their own; staff see open ones plus those assigned to them; admins see all."""
    resident_id = user.get("resident_id") if user["role"] == "resident" else None
    if user["role"] == "resident" and resident_id is None:
        return []
    staff_id = user["id"] if user["role"] == "maintenance_staff" else None
    return [dict(row) for row in db.execute(text("""
        SELECT c.id, c.subject, c.category, c.priority, c.status, c.submitted_at, c.assigned_to,
               r.full_name AS resident_name, h.name AS hostel, rm.room_number, s.full_name AS assigned_name
        FROM complaints c
        JOIN residents r ON r.id = c.resident_id
        LEFT JOIN rooms rm ON rm.id = c.room_id
        LEFT JOIN hostels h ON h.id = rm.hostel_id
        LEFT JOIN users s ON s.id = c.assigned_to
        WHERE (:resident_id IS NULL OR c.resident_id = :resident_id)
          AND (:staff_id IS NULL OR c.assigned_to = :staff_id OR c.status = 'open')
        ORDER BY FIELD(c.status, 'open', 'assigned', 'in_progress', 'resolved', 'closed'),
                 FIELD(c.priority, 'urgent', 'high', 'medium', 'low'), c.submitted_at DESC
        LIMIT 200
    """), {"resident_id": resident_id, "staff_id": staff_id}).mappings().all()]


@app.post("/api/complaints", status_code=201)
def create_complaint(payload: ComplaintCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user["role"] == "maintenance_staff":
        raise HTTPException(status_code=403, detail="Maintenance staff cannot file complaints")
    if user["role"] == "resident" and payload.resident_id != user.get("resident_id"):
        raise HTTPException(status_code=403, detail="Residents may only submit their own complaints")
    if payload.category not in {"electrical", "plumbing", "cleaning", "furniture", "internet", "security", "other"}:
        raise HTTPException(status_code=422, detail="Invalid complaint category")
    if payload.priority not in {"low", "medium", "high", "urgent"}:
        raise HTTPException(status_code=422, detail="Invalid complaint priority")
    data = payload.model_dump()
    if data["room_id"] is None and data["bed_id"] is None:  # default to the resident's current room/bed
        current = db.execute(text("SELECT b.id AS bed_id, b.room_id FROM allocations a JOIN beds b ON b.id=a.bed_id "
                                  "WHERE a.resident_id=:r AND a.status='active'"), {"r": payload.resident_id}).mappings().one_or_none()
        if current:
            data["room_id"], data["bed_id"] = current["room_id"], current["bed_id"]
    try:
        row = db.execute(text("""
            INSERT INTO complaints (resident_id, room_id, bed_id, category, subject, description, priority)
            VALUES (:resident_id, :room_id, :bed_id, :category, :subject, :description, :priority)
        """), data)
        db.execute(text("INSERT INTO complaint_updates (complaint_id, changed_by, old_status, new_status, remark) "
                        "VALUES (:c, :u, NULL, 'open', 'Complaint submitted')"), {"c": row.lastrowid, "u": user["id"]})
        log_activity(db, user["id"], "complaint.created", "complaint", row.lastrowid, {"priority": payload.priority})
        db.commit()
        return {"id": row.lastrowid, **data, "status": "open"}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="Complaint could not be created") from exc


@app.patch("/api/complaints/{complaint_id}")
def update_complaint(complaint_id: int, payload: ComplaintUpdate, user: dict = Depends(staff_user),
                     db: Session = Depends(get_db)) -> dict:
    """Moves a complaint one step: open -> assigned -> in_progress -> resolved -> closed.
    Moving to 'assigned' sets the assignee (admin picks one; staff take it themselves)."""
    try:
        current = db.execute(text("""
            SELECT c.status, c.assigned_to, c.subject, r.user_id AS resident_user_id
            FROM complaints c JOIN residents r ON r.id=c.resident_id WHERE c.id=:id FOR UPDATE OF c
        """), {"id": complaint_id}).mappings().one_or_none()
        if not current:
            raise HTTPException(status_code=404, detail="Complaint not found")
        if payload.status not in COMPLAINT_FLOW.get(current["status"], set()):
            raise HTTPException(status_code=422, detail=f"Cannot move a complaint from '{current['status']}' to '{payload.status}'")
        assignee = current["assigned_to"]
        if payload.status == "assigned":
            assignee = user["id"] if user["role"] == "maintenance_staff" else payload.assigned_to
            if not assignee:
                raise HTTPException(status_code=422, detail="Select a maintenance staff member to assign")
            valid = db.execute(text("SELECT id FROM users WHERE id=:id AND role='maintenance_staff' AND is_active=1"),
                               {"id": assignee}).first()
            if not valid:
                raise HTTPException(status_code=422, detail="Assignee must be an active maintenance staff member")
        elif user["role"] == "maintenance_staff" and current["assigned_to"] != user["id"]:
            raise HTTPException(status_code=403, detail="Only the assigned staff member can update this complaint")
        db.execute(text("""
            UPDATE complaints SET status=:status, assigned_to=:assignee,
                   resolved_at=IF(:status='resolved', CURRENT_TIMESTAMP, resolved_at)
            WHERE id=:id
        """), {"status": payload.status, "assignee": assignee, "id": complaint_id})
        db.execute(text("INSERT INTO complaint_updates (complaint_id, changed_by, old_status, new_status, remark) "
                        "VALUES (:id, :u, :old, :new, :remark)"),
                   {"id": complaint_id, "u": user["id"], "old": current["status"], "new": payload.status, "remark": payload.remark})
        log_activity(db, user["id"], "complaint.status", "complaint", complaint_id,
                     {"from": current["status"], "to": payload.status})
        pretty = payload.status.replace("_", " ")
        notify(db, current["resident_user_id"], "Complaint update", f"'{current['subject']}' is now {pretty}.")
        if payload.status == "assigned" and user["role"] == "administrator":
            notify(db, assignee, "New assignment", f"You were assigned: {current['subject']}")
        db.commit()
        return {"id": complaint_id, "status": payload.status, "assigned_to": assignee}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Complaint update failed") from exc


@app.delete("/api/complaints/{complaint_id}")
def delete_complaint(complaint_id: int, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("DELETE FROM complaint_updates WHERE complaint_id=:id"), {"id": complaint_id})
        result = db.execute(text("DELETE FROM complaints WHERE id=:id"), {"id": complaint_id})
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="Complaint not found")
        log_activity(db, user["id"], "complaint.deleted", "complaint", complaint_id)
        db.commit()
        return {"id": complaint_id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Complaint could not be removed") from exc


# --------------------------------------------------------------------------- #
# Fees
# --------------------------------------------------------------------------- #
@app.get("/api/invoices")
def invoices(user: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    if user["role"] == "maintenance_staff":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    resident_id = user.get("resident_id") if user["role"] == "resident" else None
    if user["role"] == "resident" and resident_id is None:
        return []
    return [dict(row) for row in db.execute(text("""
        SELECT i.id, i.fee_period, i.amount_due, i.due_date,
               CASE WHEN i.status IN ('unpaid', 'partially_paid') AND i.due_date < CURDATE()
                    THEN 'overdue' ELSE i.status END AS status,
               r.full_name AS resident_name, COALESCE(SUM(p.amount), 0) AS paid,
               i.amount_due - COALESCE(SUM(p.amount), 0) AS outstanding
        FROM fee_invoices i JOIN residents r ON r.id=i.resident_id AND r.is_active=1
        LEFT JOIN payments p ON p.invoice_id=i.id
        WHERE (:resident_id IS NULL OR i.resident_id = :resident_id)
        GROUP BY i.id, r.full_name ORDER BY i.due_date DESC, i.id DESC LIMIT 300
    """), {"resident_id": resident_id}).mappings().all()]


@app.post("/api/invoices/generate")
def generate_invoices(user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    """Explicit action (replaces the old hidden side effect on GET /fees)."""
    try:
        created = ensure_current_invoices(db)
        log_activity(db, user["id"], "invoices.generated", "invoice", None, {"created": created})
        db.commit()
        return {"created": created, "period": date.today().strftime("%B %Y")}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invoices could not be generated") from exc


@app.post("/api/invoices", status_code=201)
def create_invoice(payload: InvoiceCreate, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        row = db.execute(text("INSERT INTO fee_invoices (resident_id, fee_period, amount_due, due_date) "
                              "VALUES (:resident_id, :fee_period, :amount_due, :due_date)"), payload.model_dump())
        log_activity(db, user["id"], "invoice.created", "invoice", row.lastrowid)
        db.commit()
        return {"id": row.lastrowid, **payload.model_dump(mode="json"), "status": "unpaid"}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invoice could not be created") from exc


@app.post("/api/invoices/{invoice_id}/payments", status_code=201)
def record_payment(invoice_id: int, payload: PaymentCreate, user: dict = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict:
    """Records a payment. The caller must confirm with their own account password."""
    if user["role"] != "administrator" and not (user["role"] == "resident" and user.get("resident_id")):
        raise HTTPException(status_code=403, detail="Payment permission required")
    if not check_password(db, user["id"], payload.transaction_password):
        raise HTTPException(status_code=403, detail="Incorrect password. Payment was not recorded.")
    amount = payload.amount.quantize(CENT)
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be at least 0.01")
    try:
        invoice = db.execute(text("SELECT i.id, i.resident_id, i.amount_due, r.user_id FROM fee_invoices i "
                                  "JOIN residents r ON r.id=i.resident_id WHERE i.id=:id FOR UPDATE OF i"),
                             {"id": invoice_id}).mappings().one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        if user["role"] == "resident" and invoice["resident_id"] != user["resident_id"]:
            raise HTTPException(status_code=403, detail="Residents may only pay their own invoices")
        paid = Decimal(db.execute(text("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE invoice_id=:id"),
                                  {"id": invoice_id}).scalar_one())
        due = Decimal(invoice["amount_due"])
        if paid + amount > due:
            raise HTTPException(status_code=422, detail=f"Payment exceeds outstanding balance ({due - paid})")
        reference = payload.payment_reference or f"TXN-{invoice_id}-{uuid4().hex[:10].upper()}"
        row = db.execute(text("INSERT INTO payments (invoice_id, recorded_by, amount, payment_reference) "
                              "VALUES (:invoice_id, :user_id, :amount, :ref)"),
                         {"invoice_id": invoice_id, "user_id": user["id"], "amount": amount, "ref": reference})
        status_value = "paid" if paid + amount >= due else "partially_paid"
        db.execute(text("UPDATE fee_invoices SET status=:status WHERE id=:id"), {"status": status_value, "id": invoice_id})
        log_activity(db, user["id"], "payment.recorded", "payment", row.lastrowid, {"invoice_id": invoice_id, "amount": amount})
        notify(db, invoice["user_id"], "Payment received", f"₹{amount} received. Invoice is {status_value.replace('_', ' ')}.")
        db.commit()
        return {"id": row.lastrowid, "invoice_id": invoice_id, "amount": amount,
                "payment_reference": reference, "invoice_status": status_value}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment could not be recorded") from exc


@app.post("/api/invoices/{invoice_id}/mark-paid", status_code=201)
def mark_invoice_paid(invoice_id: int, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        invoice = db.execute(text("SELECT id, amount_due FROM fee_invoices WHERE id=:id FOR UPDATE"),
                             {"id": invoice_id}).mappings().one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        paid = Decimal(db.execute(text("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE invoice_id=:id"),
                                  {"id": invoice_id}).scalar_one())
        outstanding = Decimal(invoice["amount_due"]) - paid
        if outstanding <= 0:
            raise HTTPException(status_code=409, detail="Invoice is already paid")
        reference = f"ADMIN-PAID-{invoice_id}-{uuid4().hex[:10].upper()}"
        db.execute(text("INSERT INTO payments (invoice_id, recorded_by, amount, payment_reference) "
                        "VALUES (:invoice_id, :user_id, :amount, :reference)"),
                   {"invoice_id": invoice_id, "user_id": user["id"], "amount": outstanding, "reference": reference})
        db.execute(text("UPDATE fee_invoices SET status='paid' WHERE id=:id"), {"id": invoice_id})
        log_activity(db, user["id"], "invoice.marked_paid", "invoice", invoice_id, {"amount": outstanding})
        db.commit()
        return {"invoice_id": invoice_id, "amount": outstanding, "payment_reference": reference, "invoice_status": "paid"}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invoice could not be marked as paid") from exc


@app.post("/api/invoices/{invoice_id}/remove-payment")
def remove_invoice_payment(invoice_id: int, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        invoice = db.execute(text("SELECT id, status FROM fee_invoices WHERE id=:id FOR UPDATE"),
                             {"id": invoice_id}).mappings().one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        if invoice["status"] not in {"paid", "partially_paid"}:
            raise HTTPException(status_code=409, detail="Invoice has no payment to remove")
        db.execute(text("DELETE FROM payments WHERE invoice_id=:id"), {"id": invoice_id})
        db.execute(text("UPDATE fee_invoices SET status='unpaid' WHERE id=:id"), {"id": invoice_id})
        log_activity(db, user["id"], "invoice.payments_removed", "invoice", invoice_id)
        db.commit()
        return {"invoice_id": invoice_id, "invoice_status": "unpaid"}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment status could not be removed") from exc


@app.delete("/api/invoices/{invoice_id}")
def delete_invoice(invoice_id: int, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("DELETE FROM payments WHERE invoice_id=:id"), {"id": invoice_id})
        result = db.execute(text("DELETE FROM fee_invoices WHERE id=:id"), {"id": invoice_id})
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="Invoice not found")
        log_activity(db, user["id"], "invoice.deleted", "invoice", invoice_id)
        db.commit()
        return {"id": invoice_id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invoice could not be removed") from exc


# --------------------------------------------------------------------------- #
# Notifications + reports
# --------------------------------------------------------------------------- #
@app.get("/api/notifications")
def notifications(user: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT id, title, message, is_read, created_at FROM notifications
        WHERE user_id=:user_id ORDER BY created_at DESC, id DESC LIMIT 50
    """), {"user_id": user["id"]}).mappings().all()]


@app.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    result = db.execute(text("UPDATE notifications SET is_read=1 WHERE id=:id AND user_id=:user_id"),
                        {"id": notification_id, "user_id": user["id"]})
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"id": notification_id, "is_read": True}


@app.get("/api/reports/occupancy")
def occupancy_report(_: dict = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT h.name AS hostel, COUNT(b.id) total_beds,
               COALESCE(SUM(a.id IS NOT NULL), 0) occupied_beds,
               COALESCE(SUM(b.status='available' AND a.id IS NULL), 0) available_beds,
               COALESCE(ROUND(100 * SUM(a.id IS NOT NULL) / NULLIF(COUNT(b.id), 0), 1), 0) occupancy_percent
        FROM hostels h LEFT JOIN rooms r ON r.hostel_id=h.id AND r.is_active=1
        LEFT JOIN beds b ON b.room_id=r.id AND b.status <> 'retired'
        LEFT JOIN allocations a ON a.bed_id=b.id AND a.status='active'
        WHERE h.is_active=1
        GROUP BY h.id, h.name ORDER BY h.name
    """)).mappings().all()]
