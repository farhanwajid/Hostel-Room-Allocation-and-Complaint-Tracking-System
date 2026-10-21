from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db import engine, get_db

settings = get_settings()
password_hasher = PasswordHasher()
DEFAULT_FEE_AMOUNT = 420


def ensure_pricing_columns() -> None:
    with engine.begin() as connection:
        for table, column in (("rooms", "monthly_amount"), ("beds", "monthly_amount"), ("allocations", "monthly_amount")):
            try:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} DECIMAL(12,2) NOT NULL DEFAULT 0"))
            except SQLAlchemyError:
                continue
        connection.execute(text("UPDATE rooms SET monthly_amount=420 WHERE monthly_amount=0"))
        connection.execute(text("UPDATE beds SET monthly_amount=420 WHERE monthly_amount=0"))


def initialize_pricing_schema() -> None:
    ensure_pricing_columns()


def ensure_current_invoices(db: Session, resident_id: int | None = None) -> None:
    period = date.today().strftime("%B %Y")
    params = {"period": period, "amount": DEFAULT_FEE_AMOUNT, "due_date": date.today().replace(day=5)}
    filter_sql = "WHERE is_active=1"
    if resident_id is not None:
        filter_sql += " AND id=:resident_id"
        params["resident_id"] = resident_id
    db.execute(text(f"""
        INSERT INTO fee_invoices (resident_id, fee_period, amount_due, due_date, status)
        SELECT id, :period, :amount, :due_date, 'unpaid'
        FROM residents
        {filter_sql}
        ON DUPLICATE KEY UPDATE resident_id=VALUES(resident_id)
    """), params)


def academic_end_date(start_date: date, academic_year: int) -> date:
    years_remaining = max(1, 5 - academic_year)
    try:
        return start_date.replace(year=start_date.year + years_remaining)
    except ValueError:
        return start_date.replace(month=2, day=28, year=start_date.year + years_remaining)


def auto_assign_unallocated(db: Session, admin_id: int) -> None:
    residents = db.execute(text("""
        SELECT r.id, r.academic_year
        FROM residents r
        LEFT JOIN allocations a ON a.resident_id=r.id AND a.status='active'
        WHERE r.is_active=1 AND r.eligibility_status IN ('eligible', 'pending') AND a.id IS NULL
        ORDER BY r.id
    """)).mappings().all()
    for resident in residents:
        bed = db.execute(text("""
            SELECT b.id, b.monthly_amount
            FROM beds b
            WHERE b.status='available'
              AND NOT EXISTS (SELECT 1 FROM allocations a WHERE a.bed_id=b.id AND a.status='active')
            ORDER BY b.id LIMIT 1 FOR UPDATE
        """)).mappings().one_or_none()
        if not bed:
            break
        start_date = date.today()
        end_date = academic_end_date(start_date, resident["academic_year"])
        db.execute(text("""
            INSERT INTO allocations (resident_id, bed_id, allocated_by, start_date, end_date, monthly_amount, status)
            VALUES (:resident_id, :bed_id, :admin_id, :start_date, :end_date, :amount, 'active')
        """), {"resident_id": resident["id"], "bed_id": bed["id"], "admin_id": admin_id, "start_date": start_date, "end_date": end_date, "amount": bed["monthly_amount"]})
        db.execute(text("""
            UPDATE fee_invoices SET amount_due=:amount
            WHERE resident_id=:resident_id AND status='unpaid' AND fee_period=:period
        """), {"amount": bed["monthly_amount"], "resident_id": resident["id"], "period": date.today().strftime("%B %Y")})
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="REST API for hostel allocations, complaints, and fee management.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.on_event("startup")
def _startup_pricing_schema() -> None:
    initialize_pricing_schema()


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@app.get("/health/database", tags=["system"])
def database_health_check() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise RuntimeError("Database health check failed") from exc
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
        text("SELECT u.id, u.full_name, u.email, u.role, u.is_active, r.id AS resident_id FROM users u LEFT JOIN residents r ON r.user_id = u.id WHERE u.id = :id"),
        {"id": user_id},
    ).mappings().one_or_none()
    if not user or not user["is_active"]:
        raise credentials_error
    return dict(user)


def authenticate_user(email: str, password: str, db: Session) -> dict:
    try:
        user = db.execute(
            text("SELECT id, full_name, email, password_hash, role, is_active FROM users WHERE email = :email"),
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


@app.post("/api/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> dict:
    user = authenticate_user(form.username, form.password, db)
    return {"access_token": create_token(user["id"], user["role"]), "token_type": "bearer", "user": UserOut(**user)}


@app.post("/auth/login")
def login_json(payload: LoginJson, db: Session = Depends(get_db)) -> dict:
    user = authenticate_user(payload.email, payload.password, db)
    return {"access_token": create_token(user["id"], user["role"]), "token_type": "bearer", "user": UserOut(**user)}


@app.post("/api/auth/register", status_code=201)
@app.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    try:
        with db.begin():
            existing = db.execute(
                text("SELECT id FROM users WHERE email=:email UNION SELECT user_id FROM residents WHERE email=:email"),
                {"email": payload.email},
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="An account with this email already exists")
            user_result = db.execute(
                text("""
                    INSERT INTO users (full_name, email, password_hash, role)
                    VALUES (:full_name, :email, :password_hash, 'resident')
                """),
                {
                    "full_name": payload.full_name,
                    "email": payload.email,
                    "password_hash": password_hasher.hash(payload.password),
                },
            )
            resident_result = db.execute(
                text("""
                    INSERT INTO residents
                      (user_id, roll_number, full_name, email, phone, course, academic_year, eligibility_status)
                    VALUES
                      (:user_id, :roll_number, :full_name, :email, :phone, :course, :academic_year, 'eligible')
                """),
                {"user_id": user_result.lastrowid, **payload.model_dump(exclude={"password"})},
            )
            ensure_current_invoices(db, resident_result.lastrowid)
        user = db.execute(
            text("SELECT u.id, u.full_name, u.email, u.role, r.id AS resident_id FROM users u LEFT JOIN residents r ON r.user_id=u.id WHERE u.id=:id"),
            {"id": user_result.lastrowid},
        ).mappings().one()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account could not be created; check unique details") from exc
    return {
        "access_token": create_token(user["id"], user["role"]),
        "token_type": "bearer",
        "user": UserOut(**user),
    }


@app.get("/api/auth/me", response_model=UserOut)
def me(user: dict = Depends(current_user)) -> dict:
    return user


@app.get("/api/dashboard/stats", response_model=DashboardStats)
def dashboard_stats(_: dict = Depends(current_user), db: Session = Depends(get_db)) -> DashboardStats:
    try:
        row = db.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM residents WHERE is_active = 1) residents,
              (SELECT COUNT(*) FROM rooms WHERE is_active = 1) rooms,
              (SELECT COUNT(*) FROM beds WHERE status <> 'retired') beds,
              (SELECT COUNT(*) FROM allocations WHERE status = 'active') occupied_beds,
              (SELECT COUNT(*) FROM beds WHERE status = 'available') available_beds,
              (SELECT COUNT(*) FROM complaints WHERE status NOT IN ('resolved', 'closed')) open_complaints,
              (SELECT COUNT(*) FROM complaints WHERE priority = 'urgent' AND status NOT IN ('resolved', 'closed')) urgent_complaints,
              (SELECT COUNT(*) FROM complaints WHERE status IN ('resolved', 'closed')) resolved_complaints,
              (SELECT COUNT(*) FROM complaints WHERE status IN ('assigned', 'in_progress')) in_progress_complaints,
              (SELECT COALESCE(SUM(i.amount_due - COALESCE(p.paid, 0)), 0)
                 FROM fee_invoices i
                 LEFT JOIN (SELECT invoice_id, SUM(amount) paid FROM payments GROUP BY invoice_id) p
                   ON p.invoice_id = i.id
                WHERE i.status <> 'cancelled') outstanding_balance,
              (SELECT COUNT(*) FROM residents WHERE is_active = 1) total_residents
        """)).mappings().one()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Dashboard data is unavailable") from exc
    total = int(row["beds"] or 0)
    occupied = int(row["occupied_beds"] or 0)
    return DashboardStats(**row, occupancy_percent=round(occupied / total * 100, 1) if total else 0)


@app.get("/api/dashboard/activity")
def dashboard_activity(_: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT 'Allocation' AS type, CONCAT('Allocation for ', r.full_name) AS title,
               CONCAT('Room ', rm.room_number, ', Bed ', b.bed_number) AS description,
               a.created_at AS occurred_at
        FROM allocations a JOIN residents r ON r.id=a.resident_id
        JOIN beds b ON b.id=a.bed_id JOIN rooms rm ON rm.id=b.room_id
        UNION ALL
        SELECT 'Complaint', CONCAT('Complaint: ', subject), status, submitted_at
        FROM complaints
        UNION ALL
        SELECT 'Payment', CONCAT('Payment received from ', r.full_name),
               CONCAT('₹', p.amount), p.paid_at
        FROM payments p JOIN fee_invoices i ON i.id=p.invoice_id
        JOIN residents r ON r.id=i.resident_id
        ORDER BY occurred_at DESC LIMIT 6
    """)).mappings().all()]


@app.get("/complaints")
@app.get("/api/complaints")
def complaints(user: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    query = """
        SELECT c.id, c.subject, c.category, c.priority, c.status, c.submitted_at,
               r.full_name AS resident_name, h.name AS hostel, rm.room_number
        FROM complaints c
        JOIN residents r ON r.id = c.resident_id
        LEFT JOIN rooms rm ON rm.id = c.room_id
        LEFT JOIN hostels h ON h.id = rm.hostel_id
        WHERE (:resident_id IS NULL OR c.resident_id = :resident_id)
        ORDER BY FIELD(c.priority, 'urgent', 'high', 'medium', 'low'), c.submitted_at DESC
        LIMIT 100
    """
    resident_id = user.get("resident_id") if user["role"] == "resident" else None
    return [dict(row) for row in db.execute(text(query), {"resident_id": resident_id}).mappings().all()]


@app.get("/api/residents")
@app.get("/residents")
def residents(_: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT r.id, r.roll_number, r.full_name, r.email, r.course, r.academic_year,
               r.eligibility_status, a.status AS allocation_status
        FROM residents r
        LEFT JOIN allocations a ON a.resident_id = r.id AND a.status = 'active'
        WHERE r.is_active = 1 ORDER BY r.full_name
    """)).mappings().all()]


@app.get("/allocations")
@app.get("/api/allocations")
def allocations(user: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    if user["role"] == "administrator":
        auto_assign_unallocated(db, user["id"])
        db.commit()
    return [dict(row) for row in db.execute(text("""
        SELECT a.id, res.full_name AS resident_name, h.name AS hostel,
               r.room_number, b.bed_number, a.start_date, a.end_date, a.status,
               a.monthly_amount
        FROM allocations a JOIN residents res ON res.id=a.resident_id
        JOIN beds b ON b.id=a.bed_id JOIN rooms r ON r.id=b.room_id
        JOIN hostels h ON h.id=r.hostel_id ORDER BY a.start_date DESC LIMIT 100
    """)).mappings().all()]


class ResidentCreate(BaseModel):
    roll_number: str = Field(min_length=1, max_length=40)
    full_name: str = Field(min_length=1, max_length=120)
    email: str
    course: str
    academic_year: int = Field(ge=1, le=8)
    phone: str | None = None


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


class InvoiceCreate(BaseModel):
    resident_id: int
    fee_period: str
    amount_due: float = Field(gt=0)
    due_date: str


class PaymentCreate(BaseModel):
    amount: float = Field(gt=0)
    payment_reference: str | None = Field(default=None, max_length=80)
    transaction_password: str = Field(min_length=1, max_length=120)


class HostelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=255)
    description: str | None = None


class RoomCreate(BaseModel):
    hostel_id: int
    room_number: str = Field(min_length=1, max_length=20)
    floor: int
    room_type: str = "double"
    monthly_amount: float = Field(ge=0)
    bed_number: str | None = None
    bed_amount: float | None = Field(default=None, ge=0)
    bed_count: int = Field(default=1, ge=1, le=100)


class BedCreate(BaseModel):
    room_id: int
    bed_number: str = Field(min_length=1, max_length=20)
    status: str = "available"
    monthly_amount: float = Field(ge=0)


def require_admin(user: dict) -> dict:
    if user["role"] != "administrator":
        raise HTTPException(status_code=403, detail="Administrator permission required")
    return user


@app.get("/api/hostels")
def hostels(_: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT h.id, h.name, h.location, h.description, COUNT(DISTINCT r.id) rooms,
               COUNT(b.id) beds, SUM(b.status = 'available') available_beds
        FROM hostels h LEFT JOIN rooms r ON r.hostel_id=h.id AND r.is_active=1
        LEFT JOIN beds b ON b.room_id=r.id
        WHERE h.is_active=1 GROUP BY h.id ORDER BY h.name
    """)).mappings().all()]


@app.post("/api/hostels", status_code=201)
def create_hostel(payload: HostelCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        result = db.execute(text("INSERT INTO hostels (name, location, description) VALUES (:name, :location, :description)"), payload.model_dump())
        db.commit()
        return {"id": result.lastrowid, **payload.model_dump()}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Hostel name already exists") from exc


@app.get("/rooms")
@app.get("/api/rooms")
def rooms(_: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
    SELECT r.id, r.room_number, r.floor, r.room_type, r.monthly_amount, h.name AS hostel,
               COUNT(b.id) beds, COALESCE(SUM(b.status='available'), 0) available_beds,
               COALESCE(MIN(b.monthly_amount), r.monthly_amount) bed_monthly_amount,
               COUNT(a.id) occupied_beds
        FROM rooms r JOIN hostels h ON h.id=r.hostel_id
        LEFT JOIN beds b ON b.room_id=r.id
        LEFT JOIN allocations a ON a.bed_id=b.id AND a.status='active'
        WHERE r.is_active=1 GROUP BY r.id ORDER BY h.name, r.room_number
    """)).mappings().all()]


@app.post("/api/rooms", status_code=201)
def create_room(payload: RoomCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        result = db.execute(text("INSERT INTO rooms (hostel_id, room_number, floor, room_type, monthly_amount) VALUES (:hostel_id, :room_number, :floor, :room_type, :monthly_amount)"), payload.model_dump())
        if payload.bed_number:
            first_bed = payload.bed_number.strip()
            numeric_bed = first_bed.isdigit()
            for offset in range(payload.bed_count):
                if numeric_bed:
                    bed_number = str(int(first_bed) + offset)
                elif len(first_bed) == 1 and first_bed.isalpha():
                    bed_number = chr(ord(first_bed.upper()) + offset)
                else:
                    bed_number = first_bed if offset == 0 else f"{first_bed}-{offset + 1}"
                db.execute(text("INSERT INTO beds (room_id, bed_number, status, monthly_amount) VALUES (:room_id, :bed_number, 'available', :bed_amount)"), {"room_id": result.lastrowid, "bed_number": bed_number, "bed_amount": payload.bed_amount if payload.bed_amount is not None else payload.monthly_amount})
        db.commit()
        return {"id": result.lastrowid, **payload.model_dump()}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Room number already exists in this hostel") from exc


@app.delete("/api/rooms/{room_id}")
def delete_room(room_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        allocation_ids = db.execute(text("SELECT id FROM allocations WHERE bed_id IN (SELECT id FROM beds WHERE room_id=:id)"), {"id": room_id}).scalars().all()
        for allocation_id in allocation_ids:
            db.execute(text("DELETE FROM room_transfers WHERE from_allocation_id=:id OR to_allocation_id=:id"), {"id": allocation_id})
        db.execute(text("DELETE FROM complaint_updates WHERE complaint_id IN (SELECT id FROM complaints WHERE room_id=:id)"), {"id": room_id})
        db.execute(text("DELETE FROM complaints WHERE room_id=:id"), {"id": room_id})
        db.execute(text("DELETE FROM allocations WHERE bed_id IN (SELECT id FROM beds WHERE room_id=:id)"), {"id": room_id})
        db.execute(text("DELETE FROM beds WHERE room_id=:id"), {"id": room_id})
        result = db.execute(text("DELETE FROM rooms WHERE id=:id"), {"id": room_id})
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="Room not found")
        db.commit()
        return {"id": room_id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Room could not be removed") from exc


@app.get("/beds")
@app.get("/api/beds")
def beds(_: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
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
def create_bed(payload: BedCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    if payload.status not in {"available", "maintenance", "retired"}:
        raise HTTPException(status_code=422, detail="Invalid bed status")
    try:
        result = db.execute(text("INSERT INTO beds (room_id, bed_number, status, monthly_amount) VALUES (:room_id, :bed_number, :status, :monthly_amount)"), payload.model_dump())
        db.commit()
        return {"id": result.lastrowid, **payload.model_dump()}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bed number already exists in this room") from exc


@app.post("/api/residents", status_code=201)
def create_resident(payload: ResidentCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        row = db.execute(text("""
            INSERT INTO residents (roll_number, full_name, email, phone, course, academic_year, eligibility_status)
            VALUES (:roll_number, :full_name, :email, :phone, :course, :academic_year, 'eligible')
        """), payload.model_dump())
        ensure_current_invoices(db, row.lastrowid)
        db.commit()
        return {"id": row.lastrowid, **payload.model_dump(), "eligibility_status": "eligible"}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Resident could not be created; check unique fields") from exc


@app.delete("/api/residents/{resident_id}")
def delete_resident(resident_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        resident = db.execute(
            text("SELECT id FROM residents WHERE id=:id FOR UPDATE"),
            {"id": resident_id},
        ).first()
        if not resident:
            raise HTTPException(status_code=404, detail="Resident not found")

        allocation_ids = db.execute(
            text("SELECT id FROM allocations WHERE resident_id=:resident_id"),
            {"resident_id": resident_id},
        ).scalars().all()
        for allocation_id in allocation_ids:
            db.execute(
                text("DELETE FROM room_transfers WHERE from_allocation_id=:id OR to_allocation_id=:id"),
                {"id": allocation_id},
            )
        db.execute(text("DELETE FROM complaint_updates WHERE complaint_id IN (SELECT id FROM complaints WHERE resident_id=:id)"), {"id": resident_id})
        db.execute(text("DELETE FROM complaints WHERE resident_id=:id"), {"id": resident_id})
        db.execute(text("DELETE FROM payments WHERE invoice_id IN (SELECT id FROM fee_invoices WHERE resident_id=:id)"), {"id": resident_id})
        db.execute(text("DELETE FROM fee_invoices WHERE resident_id=:id"), {"id": resident_id})
        db.execute(text("DELETE FROM allocations WHERE resident_id=:id"), {"id": resident_id})
        db.execute(text("DELETE FROM residents WHERE id=:id"), {"id": resident_id})
        db.commit()
        return {"id": resident_id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Resident could not be removed") from exc


@app.post("/api/allocations", status_code=201)
def allocate(payload: AllocationCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        resident = db.execute(text("SELECT id, eligibility_status, academic_year FROM residents WHERE id=:id FOR UPDATE"), {"id": payload.resident_id}).mappings().one_or_none()
        bed = db.execute(text("SELECT id, status, monthly_amount FROM beds WHERE id=:id FOR UPDATE"), {"id": payload.bed_id}).mappings().one_or_none()
        if not resident or resident["eligibility_status"] not in {"eligible", "pending"}:
            raise HTTPException(status_code=409, detail="Resident is not eligible for allocation")
        if not bed or bed["status"] != "available":
            raise HTTPException(status_code=409, detail="Bed is unavailable")
        occupied = db.execute(
            text("SELECT id FROM allocations WHERE bed_id=:bed_id AND status='active'"),
            {"bed_id": payload.bed_id},
        ).first()
        if occupied:
            raise HTTPException(status_code=409, detail="Bed already has an active allocation")
        existing = db.execute(text("SELECT id FROM allocations WHERE resident_id=:resident_id AND status='active'"), {"resident_id": payload.resident_id}).first()
        if existing:
            raise HTTPException(status_code=409, detail="Resident already has an active allocation")
        start_date = date.fromisoformat(payload.start_date)
        end_date = academic_end_date(start_date, resident["academic_year"])
        row = db.execute(text("""
            INSERT INTO allocations (resident_id, bed_id, allocated_by, start_date, end_date, monthly_amount, status)
            VALUES (:resident_id, :bed_id, :admin_id, :start_date, :end_date, :monthly_amount, 'active')
        """), {"resident_id": payload.resident_id, "bed_id": payload.bed_id, "admin_id": user["id"], "start_date": start_date, "end_date": end_date, "monthly_amount": bed["monthly_amount"]})
        db.execute(text("UPDATE fee_invoices SET amount_due=:amount WHERE resident_id=:resident_id AND status='unpaid' AND fee_period=:period"), {"amount": bed["monthly_amount"], "resident_id": payload.resident_id, "period": date.today().strftime("%B %Y")})
        db.commit()
        return {"id": row.lastrowid, "resident_id": payload.resident_id, "bed_id": payload.bed_id, "start_date": start_date, "end_date": end_date, "monthly_amount": bed["monthly_amount"], "status": "active"}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Allocation failed due to a conflicting record") from exc


@app.delete("/api/allocations/{allocation_id}")
def delete_allocation(allocation_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        db.execute(text("DELETE FROM room_transfers WHERE from_allocation_id=:id OR to_allocation_id=:id"), {"id": allocation_id})
        result = db.execute(text("DELETE FROM allocations WHERE id=:id"), {"id": allocation_id})
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="Allocation not found")
        db.commit()
        return {"id": allocation_id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Allocation could not be removed") from exc


@app.post("/api/allocations/{allocation_id}/transfer", status_code=201)
def transfer(allocation_id: int, payload: TransferCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        allocation = db.execute(text("SELECT * FROM allocations WHERE id=:id AND status='active' FOR UPDATE"), {"id": allocation_id}).mappings().one_or_none()
        bed = db.execute(text("SELECT id, status FROM beds WHERE id=:id FOR UPDATE"), {"id": payload.destination_bed_id}).mappings().one_or_none()
        if not allocation:
            raise HTTPException(status_code=404, detail="Active allocation not found")
        if not bed or bed["status"] != "available":
            raise HTTPException(status_code=409, detail="Destination bed is unavailable")
        db.execute(text("UPDATE allocations SET status='completed', end_date=CURRENT_DATE WHERE id=:id"), {"id": allocation_id})
        new_allocation = db.execute(text("""
            INSERT INTO allocations (resident_id, bed_id, allocated_by, start_date, status)
            VALUES (:resident_id, :bed_id, :admin_id, CURRENT_DATE, 'active')
        """), {"resident_id": allocation["resident_id"], "bed_id": payload.destination_bed_id, "admin_id": user["id"]})
        db.execute(text("""
            INSERT INTO room_transfers (resident_id, from_allocation_id, to_allocation_id, reason, transferred_by)
            VALUES (:resident_id, :from_id, :to_id, :reason, :admin_id)
        """), {"resident_id": allocation["resident_id"], "from_id": allocation_id, "to_id": new_allocation.lastrowid, "reason": payload.reason, "admin_id": user["id"]})
        db.commit()
        return {"from_allocation_id": allocation_id, "to_allocation_id": new_allocation.lastrowid, "status": "completed"}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Transfer failed and was rolled back") from exc


@app.post("/api/complaints", status_code=201)
def create_complaint(payload: ComplaintCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user["role"] == "resident" and payload.resident_id != user.get("resident_id"):
        raise HTTPException(status_code=403, detail="Residents may only submit their own complaints")
    if payload.category not in {"electrical", "plumbing", "cleaning", "furniture", "internet", "security", "other"}:
        raise HTTPException(status_code=422, detail="Invalid complaint category")
    if payload.priority not in {"low", "medium", "high", "urgent"}:
        raise HTTPException(status_code=422, detail="Invalid complaint priority")
    try:
        row = db.execute(text("""
            INSERT INTO complaints (resident_id, room_id, bed_id, category, subject, description, priority)
            VALUES (:resident_id, :room_id, :bed_id, :category, :subject, :description, :priority)
        """), payload.model_dump())
        db.commit()
        return {"id": row.lastrowid, **payload.model_dump(), "status": "open"}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="Complaint could not be created") from exc


@app.patch("/api/complaints/{complaint_id}", response_model=dict)
def update_complaint(complaint_id: int, payload: ComplaintUpdate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user["role"] not in {"administrator", "maintenance_staff"}:
        raise HTTPException(status_code=403, detail="Maintenance permission required")
    allowed = {"open": {"assigned"}, "assigned": {"in_progress"}, "in_progress": {"resolved"}, "resolved": {"closed"}, "closed": set()}
    current = db.execute(text("SELECT status FROM complaints WHERE id=:id FOR UPDATE"), {"id": complaint_id}).mappings().one_or_none()
    if not current:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if payload.status not in allowed.get(current["status"], set()):
        raise HTTPException(status_code=422, detail="Invalid complaint status transition")
    try:
        db.execute(text("UPDATE complaints SET status=:status, resolved_at=IF(:status='resolved', CURRENT_TIMESTAMP, resolved_at) WHERE id=:id"), {"status": payload.status, "id": complaint_id})
        db.execute(text("INSERT INTO complaint_updates (complaint_id, changed_by, old_status, new_status, remark) VALUES (:id, :user_id, :old, :new, :remark)"), {"id": complaint_id, "user_id": user["id"], "old": current["status"], "new": payload.status, "remark": payload.remark})
        db.commit()
        return {"id": complaint_id, "status": payload.status}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Complaint update failed") from exc


@app.delete("/api/complaints/{complaint_id}")
def delete_complaint(complaint_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        db.execute(text("DELETE FROM complaint_updates WHERE complaint_id=:id"), {"id": complaint_id})
        result = db.execute(text("DELETE FROM complaints WHERE id=:id"), {"id": complaint_id})
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="Complaint not found")
        db.commit()
        return {"id": complaint_id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Complaint could not be removed") from exc


@app.post("/api/invoices", status_code=201)
def create_invoice(payload: InvoiceCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        row = db.execute(text("INSERT INTO fee_invoices (resident_id, fee_period, amount_due, due_date) VALUES (:resident_id, :fee_period, :amount_due, :due_date)"), payload.model_dump())
        db.commit()
        return {"id": row.lastrowid, **payload.model_dump(), "status": "unpaid"}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invoice could not be created") from exc


@app.post("/api/invoices/{invoice_id}/payments", status_code=201)
def record_payment(invoice_id: int, payload: PaymentCreate, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user["role"] != "administrator" and not (user["role"] == "resident" and user.get("resident_id")):
        raise HTTPException(status_code=403, detail="Payment permission required")
    try:
        invoice = db.execute(text("SELECT id, resident_id, amount_due FROM fee_invoices WHERE id=:id FOR UPDATE"), {"id": invoice_id}).mappings().one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        if user["role"] == "resident" and invoice["resident_id"] != user["resident_id"]:
            raise HTTPException(status_code=403, detail="Residents may only pay their own invoices")
        paid = db.execute(text("SELECT COALESCE(SUM(amount), 0) AS paid FROM payments WHERE invoice_id=:id"), {"id": invoice_id}).scalar_one()
        if float(paid) + payload.amount > float(invoice["amount_due"]):
            raise HTTPException(status_code=422, detail="Payment exceeds outstanding balance")
        reference = payload.payment_reference or f"TXN-{invoice_id}-{uuid4().hex[:10].upper()}"
        row = db.execute(text("INSERT INTO payments (invoice_id, recorded_by, amount, payment_reference) VALUES (:invoice_id, :user_id, :amount, :payment_reference)"), {"invoice_id": invoice_id, "user_id": user["id"], "amount": payload.amount, "payment_reference": reference})
        new_paid = float(paid) + payload.amount
        status_value = "paid" if new_paid == float(invoice["amount_due"]) else "partially_paid"
        db.execute(text("UPDATE fee_invoices SET status=:status WHERE id=:id"), {"status": status_value, "id": invoice_id})
        db.commit()
        return {"id": row.lastrowid, "invoice_id": invoice_id, "amount": payload.amount, "payment_reference": reference, "invoice_status": status_value}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment could not be recorded") from exc


@app.post("/api/invoices/{invoice_id}/mark-paid", status_code=201)
def mark_invoice_paid(invoice_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        invoice = db.execute(
            text("SELECT id, amount_due FROM fee_invoices WHERE id=:id FOR UPDATE"),
            {"id": invoice_id},
        ).mappings().one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        paid = db.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE invoice_id=:id"),
            {"id": invoice_id},
        ).scalar_one()
        outstanding = float(invoice["amount_due"]) - float(paid)
        if outstanding <= 0:
            raise HTTPException(status_code=409, detail="Invoice is already paid")
        reference = f"ADMIN-PAID-{invoice_id}-{uuid4().hex[:10].upper()}"
        db.execute(
            text("INSERT INTO payments (invoice_id, recorded_by, amount, payment_reference) VALUES (:invoice_id, :user_id, :amount, :reference)"),
            {"invoice_id": invoice_id, "user_id": user["id"], "amount": outstanding, "reference": reference},
        )
        db.execute(text("UPDATE fee_invoices SET status='paid' WHERE id=:id"), {"id": invoice_id})
        db.commit()
        return {"invoice_id": invoice_id, "amount": outstanding, "payment_reference": reference, "invoice_status": "paid"}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invoice could not be marked as paid") from exc


@app.post("/api/invoices/{invoice_id}/remove-payment")
def remove_invoice_payment(invoice_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        invoice = db.execute(
            text("SELECT id, status FROM fee_invoices WHERE id=:id FOR UPDATE"),
            {"id": invoice_id},
        ).mappings().one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        if invoice["status"] not in {"paid", "partially_paid"}:
            raise HTTPException(status_code=409, detail="Invoice has no payment to remove")
        db.execute(text("DELETE FROM payments WHERE invoice_id=:id"), {"id": invoice_id})
        db.execute(text("UPDATE fee_invoices SET status='unpaid' WHERE id=:id"), {"id": invoice_id})
        db.commit()
        return {"invoice_id": invoice_id, "invoice_status": "unpaid"}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment status could not be removed") from exc


@app.delete("/api/invoices/{invoice_id}")
def delete_invoice(invoice_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    try:
        db.execute(text("DELETE FROM payments WHERE invoice_id=:id"), {"id": invoice_id})
        result = db.execute(text("DELETE FROM fee_invoices WHERE id=:id"), {"id": invoice_id})
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="Invoice not found")
        db.commit()
        return {"id": invoice_id, "deleted": True}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invoice could not be removed") from exc

@app.get("/api/invoices")
@app.get("/fees")
def invoices(user: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    resident_id = user.get("resident_id") if user["role"] == "resident" else None
    ensure_current_invoices(db, resident_id)
    db.commit()
    query = """
        SELECT i.id, i.fee_period, i.amount_due, i.due_date, i.status,
               r.full_name AS resident_name, COALESCE(SUM(p.amount), 0) AS paid,
               i.amount_due - COALESCE(SUM(p.amount), 0) AS outstanding
        FROM fee_invoices i JOIN residents r ON r.id=i.resident_id
        LEFT JOIN payments p ON p.invoice_id=i.id
        WHERE (:resident_id IS NULL OR i.resident_id = :resident_id)
        GROUP BY i.id ORDER BY i.due_date DESC
    """
    return [dict(row) for row in db.execute(text(query), {"resident_id": resident_id}).mappings().all()]


@app.get("/api/notifications")
def notifications(user: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT id, title, message, is_read, created_at FROM notifications
        WHERE user_id=:user_id ORDER BY created_at DESC LIMIT 100
    """), {"user_id": user["id"]}).mappings().all()]


@app.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    result = db.execute(text("UPDATE notifications SET is_read=1 WHERE id=:id AND user_id=:user_id"), {"id": notification_id, "user_id": user["id"]})
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"id": notification_id, "is_read": True}


@app.get("/api/reports/occupancy")
def occupancy_report(_: dict = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [dict(row) for row in db.execute(text("""
        SELECT h.name AS hostel, COUNT(b.id) total_beds,
               SUM(a.status='active') occupied_beds, SUM(b.status='available') available_beds,
               ROUND(100 * SUM(a.status='active') / NULLIF(COUNT(b.id), 0), 1) occupancy_percent
        FROM hostels h LEFT JOIN rooms r ON r.hostel_id=h.id
        LEFT JOIN beds b ON b.room_id=r.id
        LEFT JOIN allocations a ON a.bed_id=b.id AND a.status='active'
        GROUP BY h.id ORDER BY h.name
    """)).mappings().all()]
