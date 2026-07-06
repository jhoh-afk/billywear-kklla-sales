#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
from http import cookies
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.environ.get("KKLLA_DATA_DIR", ROOT / "data")).expanduser().resolve()
RUNTIME_DIR = Path(os.environ.get("KKLLA_RUNTIME_DIR", ROOT / "runtime")).expanduser().resolve()
DB_PATH = Path(os.environ.get("KKLLA_DB_PATH", DATA_DIR / "kklla.sqlite3")).expanduser().resolve()
SESSION_COOKIE = "kklla_session"
SESSION_DAYS = 14
TODAY = dt.date(2026, 7, 5)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def today_iso() -> str:
    return TODAY.isoformat()


def add_days(date_text: str, days: int) -> str:
    base = dt.date.fromisoformat(date_text[:10])
    return (base + dt.timedelta(days=days)).isoformat()


def make_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def initial_admin_password() -> str:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    password_file = RUNTIME_DIR / "admin-login.txt"
    if password_file.exists():
        text = password_file.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()

    password = secrets.token_urlsafe(18)
    password_file.write_text(
        "\n".join(
            [
                "Billywear KKLLA 관리자 초기 로그인",
                "email=admin@billywear-kklla.kr",
                f"password={password}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return password


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 240_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_account_number(value: str | None) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) <= 4:
        return "****"
    return f"{'*' * max(4, len(digits) - 4)}{digits[-4:]}"


def normalize_text(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"[\s\-().]", "", text)
    text = re.sub(r"당구클럽|당구장|클럽|아카데미|동호회", "", text)
    return text


def phone_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def duplicate_score(source: dict, target: dict) -> int:
    if source.get("id") == target.get("id"):
        return 0

    score = 0
    source_phone = phone_digits(source.get("phone"))
    target_phone = phone_digits(target.get("phone"))
    source_name = normalize_text(source.get("name"))
    target_name = normalize_text(target.get("name"))
    source_address = normalize_text(source.get("address"))
    target_address = normalize_text(target.get("address"))

    if source_phone and len(source_phone) >= 8 and source_phone == target_phone:
        score += 60
    if source_name and target_name and source_name == target_name:
        score += 35
    if source_name and target_name and (source_name in target_name or target_name in source_name):
        score += 24
    if source_address and target_address and (
        source_address in target_address or target_address in source_address
    ):
        score += 35
    if source.get("region") and source.get("region") == target.get("region"):
        score += 8
    return min(score, 100)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE,
              phone TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('manager', 'sales')),
              status TEXT NOT NULL CHECK(status IN ('active', 'pending', 'suspended')),
              region TEXT,
              coverage TEXT,
              work_type TEXT,
              transport TEXT,
              bank_name TEXT,
              account_holder TEXT,
              account_number TEXT,
              existing_network TEXT,
              agreements TEXT,
              joined_at TEXT,
              approved_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              category TEXT NOT NULL,
              region TEXT NOT NULL,
              address TEXT NOT NULL,
              contact_name TEXT,
              phone TEXT,
              owner_id TEXT NOT NULL REFERENCES users(id),
              originator_id TEXT NOT NULL REFERENCES users(id),
              status TEXT NOT NULL,
              expected_amount INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              lock_until TEXT,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS activities (
              id TEXT PRIMARY KEY,
              date TEXT NOT NULL,
              rep_id TEXT NOT NULL REFERENCES users(id),
              account_id TEXT NOT NULL REFERENCES accounts(id),
              type TEXT NOT NULL,
              contact TEXT,
              summary TEXT NOT NULL,
              next_action TEXT,
              next_date TEXT,
              location_note TEXT,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS contracts (
              id TEXT PRIMARY KEY,
              account_id TEXT NOT NULL REFERENCES accounts(id),
              date TEXT NOT NULL,
              amount INTEGER NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('pending', 'approved')),
              originator_id TEXT NOT NULL REFERENCES users(id),
              closer_id TEXT NOT NULL REFERENCES users(id),
              manager_id TEXT NOT NULL REFERENCES users(id),
              originator_share INTEGER NOT NULL,
              closer_share INTEGER NOT NULL,
              manager_share INTEGER NOT NULL,
              memo TEXT,
              created_at TEXT NOT NULL,
              approved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS audit (
              id TEXT PRIMARY KEY,
              date TEXT NOT NULL,
              actor_id TEXT REFERENCES users(id),
              action TEXT NOT NULL,
              detail TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );
            """
        )

        user_count = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        if user_count == 0:
            seed_db(db)
        else:
            sync_admin_password(db)


def sync_admin_password(db: sqlite3.Connection) -> None:
    password = os.environ.get("KKLLA_ADMIN_PASSWORD")
    if not password:
        return
    db.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = 'admin'",
        (password_hash(password), now_iso()),
    )


def seed_db(db: sqlite3.Connection) -> None:
    timestamp = now_iso()
    admin_password = os.environ.get("KKLLA_ADMIN_PASSWORD") or initial_admin_password()
    users = [
        {
            "id": "admin",
            "name": "관리자",
            "email": "admin@billywear-kklla.kr",
            "phone": "02-0000-0000",
            "password": admin_password,
            "role": "manager",
            "status": "active",
            "region": "본사",
            "coverage": "전국",
            "work_type": "관리자",
            "transport": "",
            "bank_name": "",
            "account_holder": "",
            "account_number": "",
            "existing_network": "",
            "agreements": "{}",
            "joined_at": "2026-06-01",
            "approved_at": "2026-06-01",
        },
        {
            "id": "r1",
            "name": "강도윤",
            "email": "doyun@kklla.kr",
            "phone": "010-1200-3481",
            "password": "sales2026!",
            "role": "sales",
            "status": "active",
            "region": "서울·경기",
            "coverage": "서울, 경기 북부",
            "work_type": "성과급 영업",
            "transport": "자차",
            "bank_name": "국민은행",
            "account_holder": "강도윤",
            "account_number": "123456-00-000001",
            "existing_network": "서울 강남권 당구장 8곳, 3쿠션 동호회 2곳",
            "agreements": '{"ownership": true, "settlement": true}',
            "joined_at": "2026-06-01",
            "approved_at": "2026-06-01",
        },
        {
            "id": "r2",
            "name": "박민재",
            "email": "minjae@kklla.kr",
            "phone": "010-8891-1002",
            "password": "sales2026!",
            "role": "sales",
            "status": "active",
            "region": "영남·충청",
            "coverage": "부산, 대구, 대전, 충청",
            "work_type": "성과급 영업",
            "transport": "자차",
            "bank_name": "신한은행",
            "account_holder": "박민재",
            "account_number": "110-000-000002",
            "existing_network": "부산 동호회, 대전 아카데미 네트워크",
            "agreements": '{"ownership": true, "settlement": true}',
            "joined_at": "2026-06-01",
            "approved_at": "2026-06-01",
        },
        {
            "id": "r3",
            "name": "이서현",
            "email": "seohyun@kklla.kr",
            "phone": "010-4114-7720",
            "password": "sales2026!",
            "role": "sales",
            "status": "active",
            "region": "호남·강원",
            "coverage": "전라, 광주, 강원",
            "work_type": "프리랜서",
            "transport": "혼합",
            "bank_name": "우리은행",
            "account_holder": "이서현",
            "account_number": "1002-000-000003",
            "existing_network": "전주 동호회, 강원 협회 행사 담당자",
            "agreements": '{"ownership": true, "settlement": true}',
            "joined_at": "2026-06-01",
            "approved_at": "2026-06-01",
        },
        {
            "id": "r4",
            "name": "정하준",
            "email": "hajun@example.com",
            "phone": "010-3300-9041",
            "password": "sales2026!",
            "role": "sales",
            "status": "pending",
            "region": "인천·경기 서부",
            "coverage": "인천, 부천, 김포",
            "work_type": "파트타임",
            "transport": "대중교통",
            "bank_name": "하나은행",
            "account_holder": "정하준",
            "account_number": "352-0000-000004",
            "existing_network": "인천 포켓볼 동호회 1곳",
            "agreements": '{"ownership": true, "settlement": true}',
            "joined_at": "2026-07-04",
            "approved_at": "",
        },
    ]
    for user in users:
        db.execute(
            """
            INSERT INTO users (
              id, name, email, phone, password_hash, role, status, region, coverage,
              work_type, transport, bank_name, account_holder, account_number,
              existing_network, agreements, joined_at, approved_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                user["name"],
                user["email"],
                user["phone"],
                password_hash(user["password"]),
                user["role"],
                user["status"],
                user["region"],
                user["coverage"],
                user["work_type"],
                user["transport"],
                user["bank_name"],
                user["account_holder"],
                user["account_number"],
                user["existing_network"],
                user["agreements"],
                user["joined_at"],
                user["approved_at"],
                timestamp,
                timestamp,
            ),
        )

    accounts = [
        ("a1", "강남 브레이크 당구클럽", "당구장", "서울 강남구", "서울 강남구 테헤란로 152 지하1층", "김성우 대표", "010-3412-7781", "r1", "r1", "견적중", 3600000, "2026-06-21", "2026-07-21"),
        ("a2", "부산 큐하우스", "동호회", "부산 해운대구", "부산 해운대구 센텀동로 55 2층", "최민호 총무", "010-8891-6020", "r2", "r2", "계약완료", 2800000, "2026-06-14", "2026-08-01"),
        ("a3", "대전 브릿지 3쿠션 클럽", "당구장", "대전 유성구", "대전 유성구 대학로 88 4층", "오지훈 매니저", "010-5510-2409", "r2", "r2", "샘플 전달", 1900000, "2026-06-28", "2026-07-28"),
        ("a4", "강남 브레이크 클럽", "당구장", "서울 강남구", "서울 강남구 테헤란로152 지하 1층", "김 대표", "010-3412-7781", "r3", "r3", "중복 검토", 3000000, "2026-07-03", "2026-08-02"),
        ("a5", "전주 포켓라인 동호회", "동호회", "전북 전주시", "전북 전주시 완산구 홍산중앙로 18", "문정아 회장", "010-4114-3221", "r3", "r3", "계약 협의", 4400000, "2026-06-19", "2026-07-19"),
        ("a6", "수원 퍼스트캐롬 아카데미", "프로팀", "경기 수원시", "경기 수원시 팔달구 효원로 307 3층", "한태성 감독", "010-7800-4139", "r1", "r1", "접촉중", 5200000, "2026-06-25", "2026-07-25"),
    ]
    db.executemany(
        """
        INSERT INTO accounts (
          id, name, category, region, address, contact_name, phone, owner_id,
          originator_id, status, expected_amount, created_at, lock_until, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(*account, timestamp) for account in accounts],
    )

    activities = [
        ("act1", "2026-07-04", "r1", "a1", "견적 발송", "김성우 대표", "하계 단체복 38벌 기준 견적 전달. 상의 원단과 자수 위치 확인 요청.", "7월 6일 디자인 시안 전달", "2026-07-06", "방문 후 카톡으로 견적서 공유", "2026-07-04T11:10:00"),
        ("act2", "2026-07-03", "r3", "a4", "방문", "김 대표", "신규 방문으로 등록했으나 강남 브레이크 당구클럽과 동일 연락처 확인 필요.", "관리자 중복 검토", "2026-07-05", "같은 지하층 간판 사용", "2026-07-03T16:20:00"),
        ("act3", "2026-07-02", "r2", "a2", "계약 협의", "최민호 총무", "동호회 리그복 31벌 확정. 로고 파일은 메일로 수령.", "입금 확인 후 제작 진행", "2026-07-05", "부산 출장", "2026-07-02T14:30:00"),
        ("act4", "2026-07-01", "r3", "a5", "계약 협의", "문정아 회장", "협회 행사 단체복 제안. 50벌 이상 가능성 있음.", "원단 샘플 2종 발송", "2026-07-07", "전주 미팅", "2026-07-01T17:40:00"),
        ("act5", "2026-06-30", "r2", "a3", "샘플 전달", "오지훈 매니저", "기능성 상의 샘플 전달. 여성 회원 사이즈 요청.", "추가 사이즈표 전송", "2026-07-04", "대전", "2026-06-30T13:12:00"),
        ("act6", "2026-06-29", "r1", "a6", "전화", "한태성 감독", "프로팀 연습복 제안. 하반기 대회 전 교체 검토.", "선수단 사이즈 취합 요청", "2026-07-08", "전화 상담", "2026-06-29T10:05:00"),
    ]
    db.executemany(
        """
        INSERT INTO activities (
          id, date, rep_id, account_id, type, contact, summary, next_action,
          next_date, location_note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        activities,
    )

    contracts = [
        ("c1", "a2", "2026-07-02", 2800000, "approved", "r2", "r2", "r2", 30, 50, 20, "발굴, 계약, 사후관리가 동일 담당자.", "2026-07-02T18:15:00", "2026-07-02T18:15:00"),
        ("c2", "a1", "2026-07-04", 3600000, "pending", "r1", "r3", "r1", 30, 50, 20, "기존 담당자와 최종 견적 담당자가 달라 관리자 확정 필요.", "2026-07-04T12:00:00", None),
    ]
    db.executemany(
        """
        INSERT INTO contracts (
          id, account_id, date, amount, status, originator_id, closer_id, manager_id,
          originator_share, closer_share, manager_share, memo, created_at, approved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        contracts,
    )

    audit = [
        ("log1", "2026-07-04T12:00:00", "admin", "정산 대기 등록", "강남 브레이크 당구클럽 계약 3,600,000원 배분 검토"),
        ("log2", "2026-07-03T16:20:00", "r3", "중복 의심 거래처 등록", "강남 브레이크 클럽"),
        ("log3", "2026-07-02T18:15:00", "admin", "정산 승인", "부산 큐하우스 계약 승인"),
    ]
    db.executemany(
        "INSERT INTO audit (id, date, actor_id, action, detail) VALUES (?, ?, ?, ?, ?)",
        audit,
    )


def serialize_user(row: sqlite3.Row, include_private: bool = False) -> dict:
    item = row_to_dict(row) or {}
    item.pop("password_hash", None)
    item["workType"] = item.pop("work_type", "")
    item["bankName"] = item.pop("bank_name", "")
    item["accountHolder"] = item.pop("account_holder", "")
    account_number = item.pop("account_number", "")
    item["accountNumberMasked"] = mask_account_number(account_number)
    if include_private:
        item["accountNumber"] = account_number
    item["existingNetwork"] = item.pop("existing_network", "")
    item["joinedAt"] = item.pop("joined_at", "")
    item["approvedAt"] = item.pop("approved_at", "")
    item["createdAt"] = item.pop("created_at", "")
    item["updatedAt"] = item.pop("updated_at", "")
    try:
        item["agreements"] = json.loads(item.get("agreements") or "{}")
    except json.JSONDecodeError:
        item["agreements"] = {}
    return item


def serialize_account(row: sqlite3.Row) -> dict:
    item = row_to_dict(row) or {}
    item["contactName"] = item.pop("contact_name", "")
    item["ownerId"] = item.pop("owner_id", "")
    item["originatorId"] = item.pop("originator_id", "")
    item["expectedAmount"] = item.pop("expected_amount", 0)
    item["createdAt"] = item.pop("created_at", "")
    item["lockUntil"] = item.pop("lock_until", "")
    item["updatedAt"] = item.pop("updated_at", "")
    return item


def serialize_activity(row: sqlite3.Row) -> dict:
    item = row_to_dict(row) or {}
    item["repId"] = item.pop("rep_id", "")
    item["accountId"] = item.pop("account_id", "")
    item["nextAction"] = item.pop("next_action", "")
    item["nextDate"] = item.pop("next_date", "")
    item["locationNote"] = item.pop("location_note", "")
    item["createdAt"] = item.pop("created_at", "")
    return item


def serialize_contract(row: sqlite3.Row) -> dict:
    item = row_to_dict(row) or {}
    item["accountId"] = item.pop("account_id", "")
    item["originatorId"] = item.pop("originator_id", "")
    item["closerId"] = item.pop("closer_id", "")
    item["managerId"] = item.pop("manager_id", "")
    item["shares"] = {
        "originator": item.pop("originator_share", 0),
        "closer": item.pop("closer_share", 0),
        "manager": item.pop("manager_share", 0),
    }
    item["createdAt"] = item.pop("created_at", "")
    item["approvedAt"] = item.pop("approved_at", "")
    return item


def add_audit(db: sqlite3.Connection, actor_id: str | None, action: str, detail: str) -> None:
    db.execute(
        "INSERT INTO audit (id, date, actor_id, action, detail) VALUES (?, ?, ?, ?, ?)",
        (make_id("log"), now_iso(), actor_id, action, detail),
    )


class AppHandler(BaseHTTPRequestHandler):
    server_version = "KKLLASalesServer/1.0"

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_POST(self) -> None:
        self.handle_request("POST")

    def do_PATCH(self) -> None:
        self.handle_request("PATCH")

    def do_DELETE(self) -> None:
        self.handle_request("DELETE")

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def handle_request(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/"):
                self.handle_api(method, path, parse_qs(parsed.query))
            else:
                self.serve_static(path)
        except ApiError as error:
            self.json_response({"error": error.message}, status=error.status)
        except Exception as error:  # noqa: BLE001
            self.json_response({"error": f"서버 오류: {error}"}, status=500)

    def serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        safe_path = os.path.normpath(path.lstrip("/"))
        if safe_path.startswith(".."):
            self.send_error(404)
            return

        file_path = STATIC_DIR / safe_path
        if not file_path.exists() or not file_path.is_file():
            file_path = STATIC_DIR / "index.html"
        content = file_path.read_bytes()
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def handle_api(self, method: str, path: str, query: dict) -> None:
        if method == "GET" and path == "/api/health":
            self.json_response({"ok": True, "name": "Billywear KKLLA Sales Server"})
            return
        if method == "POST" and path == "/api/login":
            self.login()
            return
        if method == "POST" and path == "/api/logout":
            self.logout()
            return
        if method == "POST" and path == "/api/signup":
            self.signup()
            return

        user = self.require_user()
        if method == "GET" and path == "/api/me":
            self.json_response({"user": serialize_user(user)})
            return
        if method == "GET" and path == "/api/bootstrap":
            self.bootstrap(user)
            return
        if method == "GET" and path == "/api/settlements":
            self.settlements(user, query)
            return
        if method == "POST" and path == "/api/accounts":
            self.create_account(user)
            return
        if method == "POST" and path == "/api/activities":
            self.create_activity(user)
            return
        if method == "POST" and path == "/api/contracts":
            self.create_contract(user)
            return

        user_status_match = re.fullmatch(r"/api/users/([^/]+)/status", path)
        if method == "PATCH" and user_status_match:
            self.update_user_status(user, user_status_match.group(1))
            return

        account_match = re.fullmatch(r"/api/accounts/([^/]+)", path)
        if method == "PATCH" and account_match:
            self.update_account(user, account_match.group(1))
            return

        contract_approve_match = re.fullmatch(r"/api/contracts/([^/]+)/approve", path)
        if method == "PATCH" and contract_approve_match:
            self.approve_contract(user, contract_approve_match.group(1))
            return

        raise ApiError(404, "요청한 API를 찾을 수 없습니다.")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise ApiError(400, "JSON 형식이 올바르지 않습니다.")

    def json_response(self, payload: dict, status: int = 200, extra_headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie(raw)
        morsel = jar.get(SESSION_COOKIE)
        if not morsel:
            return None
        return morsel.value

    def current_user(self) -> sqlite3.Row | None:
        token = self.cookie_token()
        if not token:
            return None
        token_digest = hash_token(token)
        with get_db() as db:
            row = db.execute(
                """
                SELECT users.* FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_digest, now_iso()),
            ).fetchone()
            return row

    def require_user(self) -> sqlite3.Row:
        user = self.current_user()
        if not user:
            raise ApiError(401, "로그인이 필요합니다.")
        if user["status"] != "active":
            raise ApiError(403, "활동 가능한 계정이 아닙니다.")
        return user

    def require_manager(self, user: sqlite3.Row) -> None:
        if user["role"] != "manager":
            raise ApiError(403, "관리자 권한이 필요합니다.")

    def login(self) -> None:
        data = self.read_json()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
            if not user or not verify_password(password, user["password_hash"]):
                raise ApiError(401, "이메일 또는 비밀번호가 올바르지 않습니다.")
            if user["status"] == "pending":
                raise ApiError(403, "관리자 승인 대기 중입니다.")
            if user["status"] == "suspended":
                raise ApiError(403, "중지된 계정입니다.")

            token = secrets.token_urlsafe(32)
            expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=SESSION_DAYS)
            db.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (hash_token(token), user["id"], now_iso(), expires.isoformat()),
            )
            add_audit(db, user["id"], "로그인", f"{user['name']} 계정 로그인")

        cookie = cookies.SimpleCookie()
        cookie[SESSION_COOKIE] = token
        cookie[SESSION_COOKIE]["path"] = "/"
        cookie[SESSION_COOKIE]["httponly"] = True
        cookie[SESSION_COOKIE]["samesite"] = "Lax"
        cookie[SESSION_COOKIE]["max-age"] = str(SESSION_DAYS * 24 * 60 * 60)
        self.json_response({"user": serialize_user(user)}, extra_headers={"Set-Cookie": cookie.output(header="").strip()})

    def logout(self) -> None:
        token = self.cookie_token()
        if token:
            with get_db() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
        cookie = cookies.SimpleCookie()
        cookie[SESSION_COOKIE] = ""
        cookie[SESSION_COOKIE]["path"] = "/"
        cookie[SESSION_COOKIE]["max-age"] = "0"
        cookie[SESSION_COOKIE]["httponly"] = True
        cookie[SESSION_COOKIE]["samesite"] = "Lax"
        self.json_response({"ok": True}, extra_headers={"Set-Cookie": cookie.output(header="").strip()})

    def signup(self) -> None:
        data = self.read_json()
        required = [
            "name",
            "phone",
            "email",
            "password",
            "workType",
            "region",
            "coverage",
            "transport",
            "existingNetwork",
            "bankName",
            "accountHolder",
            "accountNumber",
        ]
        missing = [field for field in required if not str(data.get(field) or "").strip()]
        if missing:
            raise ApiError(400, f"필수 입력이 빠졌습니다: {', '.join(missing)}")
        if len(data.get("password", "")) < 8:
            raise ApiError(400, "비밀번호는 8자 이상이어야 합니다.")
        if not data.get("agreeOwnership") or not data.get("agreeSettlement"):
            raise ApiError(400, "담당권과 정산 기준 동의가 필요합니다.")

        email = data["email"].strip().lower()
        phone = data["phone"].strip()
        with get_db() as db:
            existing = db.execute(
                "SELECT id FROM users WHERE lower(email) = ? OR replace(replace(phone, '-', ''), ' ', '') = ?",
                (email, phone_digits(phone)),
            ).fetchone()
            if existing:
                raise ApiError(409, "이미 등록된 이메일 또는 휴대폰입니다.")

            user_id = make_id("r")
            db.execute(
                """
                INSERT INTO users (
                  id, name, email, phone, password_hash, role, status, region, coverage,
                  work_type, transport, bank_name, account_holder, account_number,
                  existing_network, agreements, joined_at, approved_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'sales', 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                """,
                (
                    user_id,
                    data["name"].strip(),
                    email,
                    phone,
                    password_hash(data["password"]),
                    data["region"].strip(),
                    data["coverage"].strip(),
                    data["workType"].strip(),
                    data["transport"].strip(),
                    data["bankName"].strip(),
                    data["accountHolder"].strip(),
                    data["accountNumber"].strip(),
                    data["existingNetwork"].strip(),
                    json.dumps(
                        {"ownership": bool(data.get("agreeOwnership")), "settlement": bool(data.get("agreeSettlement"))}
                    ),
                    today_iso(),
                    now_iso(),
                    now_iso(),
                ),
            )
            add_audit(db, user_id, "영업사원 가입 신청", f"{data['name'].strip()} · {data['region'].strip()}")

        self.json_response({"ok": True, "status": "pending"}, status=201)

    def bootstrap(self, user: sqlite3.Row) -> None:
        with get_db() as db:
            include_all = user["role"] == "manager"
            if include_all:
                users = db.execute("SELECT * FROM users ORDER BY role, status, name").fetchall()
                accounts = db.execute("SELECT * FROM accounts ORDER BY name").fetchall()
                activities = db.execute("SELECT * FROM activities ORDER BY date DESC, created_at DESC LIMIT 250").fetchall()
                contracts = db.execute("SELECT * FROM contracts ORDER BY date DESC, created_at DESC").fetchall()
                audit = db.execute("SELECT * FROM audit ORDER BY date DESC LIMIT 120").fetchall()
            else:
                users = db.execute(
                    "SELECT * FROM users WHERE role = 'sales' AND (status = 'active' OR id = ?) ORDER BY name",
                    (user["id"],),
                ).fetchall()
                accounts = db.execute(
                    "SELECT * FROM accounts WHERE owner_id = ? OR originator_id = ? ORDER BY name",
                    (user["id"], user["id"]),
                ).fetchall()
                visible_account_ids = [row["id"] for row in accounts] or [""]
                placeholders = ",".join("?" for _ in visible_account_ids)
                activities = db.execute(
                    f"SELECT * FROM activities WHERE rep_id = ? OR account_id IN ({placeholders}) ORDER BY date DESC, created_at DESC LIMIT 250",
                    (user["id"], *visible_account_ids),
                ).fetchall()
                contracts = db.execute(
                    """
                    SELECT * FROM contracts
                    WHERE originator_id = ? OR closer_id = ? OR manager_id = ?
                    ORDER BY date DESC, created_at DESC
                    """,
                    (user["id"], user["id"], user["id"]),
                ).fetchall()
                audit = db.execute(
                    "SELECT * FROM audit WHERE actor_id = ? ORDER BY date DESC LIMIT 80",
                    (user["id"],),
                ).fetchall()

        payload = {
            "me": serialize_user(user),
            "users": [serialize_user(row) for row in users],
            "accounts": [serialize_account(row) for row in accounts],
            "activities": [serialize_activity(row) for row in activities],
            "contracts": [serialize_contract(row) for row in contracts],
            "audit": [row_to_dict(row) for row in audit],
            "today": today_iso(),
        }
        self.json_response(payload)

    def create_account(self, user: sqlite3.Row) -> None:
        data = self.read_json()
        required = ["name", "category", "region", "address", "ownerId"]
        missing = [field for field in required if not str(data.get(field) or "").strip()]
        if missing:
            raise ApiError(400, f"필수 입력이 빠졌습니다: {', '.join(missing)}")

        owner_id = data["ownerId"] if user["role"] == "manager" else user["id"]
        with get_db() as db:
            owner = db.execute("SELECT * FROM users WHERE id = ? AND role = 'sales' AND status = 'active'", (owner_id,)).fetchone()
            if not owner:
                raise ApiError(400, "활동중인 영업사원만 담당자로 지정할 수 있습니다.")

            candidate = {
                "name": data["name"].strip(),
                "address": data["address"].strip(),
                "phone": (data.get("phone") or "").strip(),
                "region": data["region"].strip(),
            }
            existing_accounts = [serialize_account(row) for row in db.execute("SELECT * FROM accounts").fetchall()]
            duplicates = [
                {"account": account, "score": duplicate_score(candidate, account)}
                for account in existing_accounts
            ]
            duplicates = [item for item in duplicates if item["score"] >= 45]
            duplicates.sort(key=lambda item: item["score"], reverse=True)
            status = "중복 검토" if duplicates and duplicates[0]["score"] >= 70 else "신규"
            account_id = make_id("a")
            db.execute(
                """
                INSERT INTO accounts (
                  id, name, category, region, address, contact_name, phone, owner_id,
                  originator_id, status, expected_amount, created_at, lock_until, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    candidate["name"],
                    data["category"].strip(),
                    candidate["region"],
                    candidate["address"],
                    (data.get("contactName") or "").strip(),
                    candidate["phone"],
                    owner_id,
                    owner_id,
                    status,
                    int(data.get("expectedAmount") or 0),
                    today_iso(),
                    add_days(today_iso(), 30),
                    now_iso(),
                ),
            )
            add_audit(
                db,
                user["id"],
                "거래처 등록" if status == "신규" else "중복 의심 거래처 등록",
                candidate["name"],
            )
            account = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()

        self.json_response(
            {
                "account": serialize_account(account),
                "duplicates": [
                    {"score": item["score"], "account": item["account"]} for item in duplicates[:5]
                ],
            },
            status=201,
        )

    def update_account(self, user: sqlite3.Row, account_id: str) -> None:
        data = self.read_json()
        with get_db() as db:
            account = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if not account:
                raise ApiError(404, "거래처를 찾을 수 없습니다.")
            if user["role"] != "manager" and account["owner_id"] != user["id"]:
                raise ApiError(403, "내 담당 거래처만 수정할 수 있습니다.")

            updates = []
            values = []
            allowed_fields = {
                "status": "status",
                "ownerId": "owner_id",
                "expectedAmount": "expected_amount",
                "lockUntil": "lock_until",
            }
            for client_field, db_field in allowed_fields.items():
                if client_field in data:
                    if client_field == "ownerId" and user["role"] != "manager":
                        raise ApiError(403, "담당자 변경은 관리자만 가능합니다.")
                    updates.append(f"{db_field} = ?")
                    values.append(data[client_field])
            if not updates:
                raise ApiError(400, "수정할 값이 없습니다.")
            updates.append("updated_at = ?")
            values.append(now_iso())
            values.append(account_id)
            db.execute(f"UPDATE accounts SET {', '.join(updates)} WHERE id = ?", values)
            add_audit(db, user["id"], "거래처 수정", account["name"])
            updated = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()

        self.json_response({"account": serialize_account(updated)})

    def create_activity(self, user: sqlite3.Row) -> None:
        data = self.read_json()
        required = ["date", "repId", "accountId", "type", "summary"]
        missing = [field for field in required if not str(data.get(field) or "").strip()]
        if missing:
            raise ApiError(400, f"필수 입력이 빠졌습니다: {', '.join(missing)}")

        rep_id = data["repId"] if user["role"] == "manager" else user["id"]
        status_map = {
            "방문": "접촉중",
            "전화": "접촉중",
            "카톡": "접촉중",
            "샘플 전달": "샘플 전달",
            "견적 발송": "견적중",
            "계약 협의": "계약 협의",
            "사후관리": "계약완료",
        }
        with get_db() as db:
            rep = db.execute("SELECT id FROM users WHERE id = ? AND role = 'sales' AND status = 'active'", (rep_id,)).fetchone()
            if not rep:
                raise ApiError(400, "활동중인 영업사원만 기록할 수 있습니다.")
            account = db.execute("SELECT * FROM accounts WHERE id = ?", (data["accountId"],)).fetchone()
            if not account:
                raise ApiError(404, "거래처를 찾을 수 없습니다.")
            if user["role"] != "manager" and account["owner_id"] != user["id"]:
                raise ApiError(403, "내 담당 거래처에만 활동을 기록할 수 있습니다.")

            activity_id = make_id("act")
            db.execute(
                """
                INSERT INTO activities (
                  id, date, rep_id, account_id, type, contact, summary, next_action,
                  next_date, location_note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activity_id,
                    data["date"],
                    rep_id,
                    data["accountId"],
                    data["type"],
                    (data.get("contact") or "").strip(),
                    data["summary"].strip(),
                    (data.get("nextAction") or "").strip(),
                    (data.get("nextDate") or "").strip(),
                    (data.get("locationNote") or "").strip(),
                    now_iso(),
                ),
            )
            db.execute(
                "UPDATE accounts SET status = ?, lock_until = ?, updated_at = ? WHERE id = ?",
                (
                    status_map.get(data["type"], account["status"]),
                    add_days(data["date"], 30),
                    now_iso(),
                    data["accountId"],
                ),
            )
            add_audit(db, user["id"], "영업 활동 저장", f"{account['name']} · {data['type']}")
            activity = db.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()

        self.json_response({"activity": serialize_activity(activity)}, status=201)

    def create_contract(self, user: sqlite3.Row) -> None:
        data = self.read_json()
        required = ["accountId", "date", "amount", "originatorId", "closerId", "managerId", "shares"]
        missing = [field for field in required if data.get(field) in (None, "")]
        if missing:
            raise ApiError(400, f"필수 입력이 빠졌습니다: {', '.join(missing)}")
        shares = data.get("shares") or {}
        originator_share = int(shares.get("originator") or 0)
        closer_share = int(shares.get("closer") or 0)
        manager_share = int(shares.get("manager") or 0)
        if originator_share + closer_share + manager_share != 100:
            raise ApiError(400, "성과 배분 합계는 100%여야 합니다.")

        with get_db() as db:
            account = db.execute("SELECT * FROM accounts WHERE id = ?", (data["accountId"],)).fetchone()
            if not account:
                raise ApiError(404, "거래처를 찾을 수 없습니다.")
            if user["role"] != "manager" and account["owner_id"] != user["id"]:
                raise ApiError(403, "내 담당 거래처 계약만 등록할 수 있습니다.")

            contract_id = make_id("c")
            db.execute(
                """
                INSERT INTO contracts (
                  id, account_id, date, amount, status, originator_id, closer_id, manager_id,
                  originator_share, closer_share, manager_share, memo, created_at, approved_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    contract_id,
                    data["accountId"],
                    data["date"],
                    int(data["amount"]),
                    data["originatorId"],
                    data["closerId"],
                    data["managerId"],
                    originator_share,
                    closer_share,
                    manager_share,
                    (data.get("memo") or "").strip(),
                    now_iso(),
                ),
            )
            db.execute(
                "UPDATE accounts SET status = '계약완료', lock_until = ?, updated_at = ? WHERE id = ?",
                (add_days(data["date"], 60), now_iso(), data["accountId"]),
            )
            add_audit(db, user["id"], "정산 대기 등록", f"{account['name']} · {int(data['amount']):,}원")
            contract = db.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()

        self.json_response({"contract": serialize_contract(contract)}, status=201)

    def approve_contract(self, user: sqlite3.Row, contract_id: str) -> None:
        self.require_manager(user)
        with get_db() as db:
            contract = db.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
            if not contract:
                raise ApiError(404, "계약을 찾을 수 없습니다.")
            db.execute(
                "UPDATE contracts SET status = 'approved', approved_at = ? WHERE id = ?",
                (now_iso(), contract_id),
            )
            account = db.execute("SELECT name FROM accounts WHERE id = ?", (contract["account_id"],)).fetchone()
            add_audit(db, user["id"], "정산 승인", f"{account['name'] if account else '거래처'} · {contract['amount']:,}원")
            updated = db.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
        self.json_response({"contract": serialize_contract(updated)})

    def update_user_status(self, user: sqlite3.Row, target_id: str) -> None:
        self.require_manager(user)
        data = self.read_json()
        status = data.get("status")
        if status not in ("active", "pending", "suspended"):
            raise ApiError(400, "상태 값이 올바르지 않습니다.")
        if target_id == user["id"]:
            raise ApiError(400, "본인 관리자 계정 상태는 변경할 수 없습니다.")
        with get_db() as db:
            target = db.execute("SELECT * FROM users WHERE id = ?", (target_id,)).fetchone()
            if not target:
                raise ApiError(404, "사용자를 찾을 수 없습니다.")
            approved_at = today_iso() if status == "active" else target["approved_at"]
            db.execute(
                "UPDATE users SET status = ?, approved_at = ?, updated_at = ? WHERE id = ?",
                (status, approved_at, now_iso(), target_id),
            )
            action = "영업사원 승인" if status == "active" else "영업사원 중지"
            add_audit(db, user["id"], action, f"{target['name']} · {target['region']}")
            updated = db.execute("SELECT * FROM users WHERE id = ?", (target_id,)).fetchone()
        self.json_response({"user": serialize_user(updated)})

    def settlements(self, user: sqlite3.Row, query: dict) -> None:
        month = (query.get("month") or [today_iso()[:7]])[0]
        with get_db() as db:
            if user["role"] == "manager":
                users = db.execute("SELECT * FROM users WHERE role = 'sales' ORDER BY name").fetchall()
                contracts = db.execute(
                    "SELECT * FROM contracts WHERE status = 'approved' AND substr(date, 1, 7) = ?",
                    (month,),
                ).fetchall()
            else:
                users = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchall()
                contracts = db.execute(
                    """
                    SELECT * FROM contracts
                    WHERE status = 'approved' AND substr(date, 1, 7) = ?
                    AND (originator_id = ? OR closer_id = ? OR manager_id = ?)
                    """,
                    (month, user["id"], user["id"], user["id"]),
                ).fetchall()

        rows = []
        for sales_user in users:
            amount = 0
            count = 0
            for contract in contracts:
                participated = False
                if contract["originator_id"] == sales_user["id"]:
                    amount += contract["amount"] * contract["originator_share"] / 100
                    participated = True
                if contract["closer_id"] == sales_user["id"]:
                    amount += contract["amount"] * contract["closer_share"] / 100
                    participated = True
                if contract["manager_id"] == sales_user["id"]:
                    amount += contract["amount"] * contract["manager_share"] / 100
                    participated = True
                if participated:
                    count += 1
            rows.append(
                {
                    "user": serialize_user(sales_user),
                    "amount": round(amount),
                    "count": count,
                }
            )
        self.json_response({"month": month, "rows": rows})


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def main() -> None:
    parser = argparse.ArgumentParser(description="Billywear KKLLA sales management server")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "4173")))
    args = parser.parse_args()

    init_db()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Billywear KKLLA server running at http://{args.host}:{args.port}")
    print(f"Database: {DB_PATH}")
    print(f"Admin login file: {RUNTIME_DIR / 'admin-login.txt'}")
    server.serve_forever()


if __name__ == "__main__":
    main()
