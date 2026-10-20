import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "mysql+pymysql://test:test@127.0.0.1:3306/hostel_management")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-tests")

import pytest
from fastapi.testclient import TestClient

from app.main import academic_end_date, app, create_token

client = TestClient(app, raise_server_exceptions=False)

PROTECTED = [
    "/api/dashboard/stats", "/api/dashboard/me", "/api/residents", "/api/rooms", "/api/beds",
    "/api/allocations", "/api/complaints", "/api/invoices", "/api/staff", "/api/reports/occupancy",
]


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_routes_need_a_token(path):
    assert client.get(path).status_code == 401


def test_garbage_token_rejected():
    assert client.get("/api/residents", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_token_is_a_string():
    assert isinstance(create_token(1, "administrator"), str)


def test_academic_end_date_by_year():
    start = date(2026, 7, 1)
    assert academic_end_date(start, 1) == date(2030, 7, 1)
    assert academic_end_date(start, 4) == date(2027, 7, 1)
    assert academic_end_date(start, 8) == date(2027, 7, 1)  # never less than one year


def test_academic_end_date_leap_day():
    assert academic_end_date(date(2024, 2, 29), 4) == date(2025, 2, 28)
