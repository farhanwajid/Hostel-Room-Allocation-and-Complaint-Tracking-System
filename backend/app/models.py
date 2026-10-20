"""SQLAlchemy mapping of database/schema.sql (used by Alembic; the API itself uses plain SQL)."""
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, JSON, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

Role = Enum("administrator", "resident", "maintenance_staff", name="user_role")
AllocationStatus = Enum("active", "completed", "cancelled", name="allocation_status")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(Role)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resident: Mapped["Resident | None"] = relationship(back_populates="user")

class Resident(Base):
    __tablename__ = "residents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    roll_number: Mapped[str] = mapped_column(String(40), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    course: Mapped[str] = mapped_column(String(120))
    academic_year: Mapped[int] = mapped_column(Integer)
    eligibility_status: Mapped[str] = mapped_column(String(20), default="pending")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped[User | None] = relationship(back_populates="resident")
    allocations: Mapped[list["Allocation"]] = relationship(back_populates="resident")

class Hostel(Base):
    __tablename__ = "hostels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    location: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rooms: Mapped[list["Room"]] = relationship(back_populates="hostel")

class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hostel_id: Mapped[int] = mapped_column(ForeignKey("hostels.id"))
    room_number: Mapped[str] = mapped_column(String(20))
    floor: Mapped[int] = mapped_column(Integer)
    room_type: Mapped[str] = mapped_column(String(20), default="double")
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    hostel: Mapped[Hostel] = relationship(back_populates="rooms")
    beds: Mapped[list["Bed"]] = relationship(back_populates="room")

class Bed(Base):
    __tablename__ = "beds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    bed_number: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="available")
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    room: Mapped[Room] = relationship(back_populates="beds")
    allocations: Mapped[list["Allocation"]] = relationship(back_populates="bed")

class Allocation(Base):
    __tablename__ = "allocations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("residents.id"))
    bed_id: Mapped[int] = mapped_column(ForeignKey("beds.id"))
    allocated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(AllocationStatus, default="active")
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    resident: Mapped[Resident] = relationship(back_populates="allocations")
    bed: Mapped[Bed] = relationship(back_populates="allocations")

class RoomTransfer(Base):
    __tablename__ = "room_transfers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("residents.id"))
    from_allocation_id: Mapped[int] = mapped_column(ForeignKey("allocations.id"))
    to_allocation_id: Mapped[int] = mapped_column(ForeignKey("allocations.id"))
    reason: Mapped[str] = mapped_column(String(500))
    transferred_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    transferred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("residents.id"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"))
    bed_id: Mapped[int | None] = mapped_column(ForeignKey("beds.id"))
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="open")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

class ComplaintUpdate(Base):
    __tablename__ = "complaint_updates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id"))
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))
    remark: Mapped[str | None] = mapped_column(Text)

class Invoice(Base):
    __tablename__ = "fee_invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("residents.id"))
    fee_period: Mapped[str] = mapped_column(String(30))
    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="unpaid")

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("fee_invoices.id"))
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    payment_reference: Mapped[str] = mapped_column(String(80), unique=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(String(500))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)
