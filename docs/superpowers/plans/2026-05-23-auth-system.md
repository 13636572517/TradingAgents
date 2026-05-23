# Auth System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 TradingAgents Web UI 添加 JWT 用户认证，保护所有 `/api/*` 路由（除登录端点外），并提供 React 登录页面和命令行用户管理脚本。

**Architecture:** FastAPI 后端用 `python-jose` 签发 HS256 JWT Token；所有受保护路由通过 `app.include_router(..., dependencies=[Depends(get_current_user)])` 统一保护；前端 `AuthContext` 管理 token，axios 拦截器自动注入 Bearer header 并处理 401；用户存储在 MySQL/SQLite `users` 表，密码用 bcrypt 哈希。

**Tech Stack:** `python-jose[cryptography]`、`passlib[bcrypt]`、`python-multipart`、React Context API、axios interceptor

---

## 文件结构

| 操作 | 文件 |
|------|------|
| 修改 | `pyproject.toml` |
| 修改 | `server/models.py` |
| **新建** | `server/auth.py` |
| **新建** | `server/routers/auth.py` |
| 修改 | `server/main.py` |
| **新建** | `manage_users.py` |
| **新建** | `tests/test_auth.py` |
| 修改 | `web/src/types.ts` |
| 修改 | `web/src/api/client.ts` |
| **新建** | `web/src/context/AuthContext.tsx` |
| **新建** | `web/src/pages/LoginPage.tsx` |
| 修改 | `web/src/App.tsx` |
| 修改 | `web/src/components/Sidebar.tsx` |

---

### Task 1: 添加 Python 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 在 pyproject.toml 的 `[project.dependencies]` 列表里追加三个依赖**

打开 `pyproject.toml`，在 `dependencies` 列表末尾（`"yfinance>=0.2.63",` 这行之后）追加：

```toml
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "python-multipart>=0.0.9",
```

修改后 dependencies 结尾应为：

```toml
    "yfinance>=0.2.63",
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "python-multipart>=0.0.9",
]
```

- [ ] **Step 2: 安装新依赖**

```bash
pip install "python-jose[cryptography]>=3.3.0" "passlib[bcrypt]>=1.7.4" "python-multipart>=0.0.9"
```

预期输出：`Successfully installed ...`（无报错）

- [ ] **Step 3: 验证可以导入**

```bash
python -c "from jose import jwt; from passlib.context import CryptContext; print('OK')"
```

预期输出：`OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(auth): add python-jose, passlib, python-multipart dependencies"
```

---

### Task 2: User 数据模型

**Files:**
- Modify: `server/models.py`
- Create: `tests/test_auth.py`（初始版本，只测 model）

- [ ] **Step 1: 在 `tests/test_auth.py` 写失败测试**

创建 `tests/test_auth.py`：

```python
# tests/test_auth.py
"""Auth system tests — use an in-memory SQLite DB via dependency override."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db
from server.main import app

# ── In-memory test DB ────────────────────────────────────────────────────────
_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(autouse=True)
def reset_db():
    """Recreate all tables before each test, drop after."""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture
def db_session(reset_db):
    session = _Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def override_db(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


client = TestClient(app, raise_server_exceptions=False)


# ── Task 2: User model ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_user_model_create(db_session):
    from server.models import User
    user = User(username="alice", hashed_password="hashed_pw")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    assert user.id is not None
    assert user.username == "alice"
    assert user.is_active is True
    assert user.created_at is not None
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_auth.py::test_user_model_create -v
```

预期：`FAILED` 或 `ERROR`（`User` 类不存在）

- [ ] **Step 3: 在 `server/models.py` 添加 User 模型**

在文件顶部 import 区添加（`datetime` 已有，无需重复）：
```python
# 已有 import，无需添加：from datetime import datetime
```

在文件末尾 `AppSettings` 类之后追加：

```python
class User(Base):
    """认证用户。密码以 bcrypt 哈希存储，不可逆。"""
    __tablename__ = "users"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    username         = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password  = Column(String(255), nullable=False)
    is_active        = Column(Boolean, default=True, nullable=False)
    created_at       = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_auth.py::test_user_model_create -v
```

预期：`PASSED`

- [ ] **Step 5: Commit**

```bash
git add server/models.py tests/test_auth.py
git commit -m "feat(auth): add User model and test scaffolding"
```

---

### Task 3: JWT 工具函数（server/auth.py）

**Files:**
- Create: `server/auth.py`
- Modify: `tests/test_auth.py`（追加 JWT 测试）

- [ ] **Step 1: 追加 JWT 测试到 `tests/test_auth.py`**

在文件末尾追加：

```python
# ── Task 3: JWT utilities ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_hash_and_verify_password():
    from server.auth import hash_password, verify_password
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


@pytest.mark.unit
def test_create_and_decode_token():
    from server.auth import create_access_token, decode_token
    token = create_access_token("alice")
    assert isinstance(token, str)
    assert decode_token(token) == "alice"


@pytest.mark.unit
def test_decode_invalid_token():
    from server.auth import decode_token
    assert decode_token("not.a.real.token") is None


@pytest.mark.unit
def test_decode_tampered_token():
    from server.auth import create_access_token, decode_token
    token = create_access_token("alice")
    tampered = token[:-5] + "XXXXX"
    assert decode_token(tampered) is None
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_auth.py -k "jwt or password" -v
```

预期：`ERROR`（`server.auth` 模块不存在）

- [ ] **Step 3: 创建 `server/auth.py`**

```python
# server/auth.py
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from server.database import get_db

_SECRET_KEY = os.environ.get("JWT_SECRET", "dev-only-secret-change-in-production")
_ALGORITHM = "HS256"
_EXPIRE_HOURS = 24

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": expire}, _SECRET_KEY, algorithm=_ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    """Return username from token, or None if invalid or expired."""
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """FastAPI dependency: extract and validate JWT, return User or raise 401."""
    from server.models import User  # late import avoids circular dependency
    username = decode_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_auth.py -k "jwt or password" -v
```

预期：全部 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add server/auth.py tests/test_auth.py
git commit -m "feat(auth): add JWT utilities (hash_password, create_access_token, decode_token)"
```

---

### Task 4: 认证路由（POST /api/auth/login，GET /api/auth/me）

**Files:**
- Create: `server/routers/auth.py`
- Modify: `tests/test_auth.py`（追加端点测试）

- [ ] **Step 1: 追加端点测试到 `tests/test_auth.py`**

在文件末尾追加：

```python
# ── Task 4: Auth endpoints ────────────────────────────────────────────────────

def _create_user(db_session, username="alice", password="password123"):
    from server.models import User
    from server.auth import hash_password
    user = User(username=username, hashed_password=hash_password(password))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.mark.unit
def test_login_success(db_session):
    _create_user(db_session)
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.unit
def test_login_wrong_password(db_session):
    _create_user(db_session)
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_login_unknown_user(db_session):
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_me_with_valid_token(db_session):
    _create_user(db_session)
    login_resp = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    token = login_resp.json()["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


@pytest.mark.unit
def test_me_without_token():
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_auth.py -k "login or test_me" -v
```

预期：`FAILED`（路由不存在，返回 404）

- [ ] **Step 3: 创建 `server/routers/auth.py`**

```python
# server/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.auth import verify_password, create_access_token, get_current_user
from server.database import get_db
from server.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    is_active: bool

    model_config = {"from_attributes": True}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已被禁用")
    return TokenResponse(access_token=create_access_token(user.username))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_auth.py -k "login or test_me" -v
```

预期：全部 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add server/routers/auth.py tests/test_auth.py
git commit -m "feat(auth): add /api/auth/login and /api/auth/me endpoints"
```

---

### Task 5: 注册路由 + 保护所有现有端点

**Files:**
- Modify: `server/main.py`
- Modify: `tests/test_auth.py`（追加受保护路由测试）

- [ ] **Step 1: 追加受保护路由测试**

在 `tests/test_auth.py` 末尾追加：

```python
# ── Task 5: Protected routes ──────────────────────────────────────────────────

@pytest.mark.unit
def test_analyses_requires_auth():
    """GET /api/analyses must return 401 without a Bearer token."""
    resp = client.get("/api/analyses")
    assert resp.status_code == 401


@pytest.mark.unit
def test_analyses_accessible_with_token(db_session):
    _create_user(db_session)
    login_resp = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    token = login_resp.json()["access_token"]
    resp = client.get("/api/analyses", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


@pytest.mark.unit
def test_search_requires_auth():
    resp = client.get("/api/search?q=test")
    assert resp.status_code == 401
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_auth.py -k "requires_auth or accessible_with" -v
```

预期：`FAILED`（当前 `/api/analyses` 不要求认证，返回 200）

- [ ] **Step 3: 修改 `server/main.py`**

将整个文件替换为：

```python
# server/main.py
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from server.auth import get_current_user
from server.database import init_db
from server.routers.auth import router as auth_router
from server.routers.analyses import router as analyses_router
from server.routers.notifications import router as notifications_router
from server.routers.settings import router as settings_router
from server.routers.search import router as search_router
from server.routers.stats import router as stats_router
from server.routers.kline import router as kline_router

app = FastAPI(title="TradingAgents Web API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "Authorization"],
)

_auth_dep = [Depends(get_current_user)]

# Public routes (no auth required)
app.include_router(auth_router)

# Protected routes
app.include_router(analyses_router,     dependencies=_auth_dep)
app.include_router(notifications_router, dependencies=_auth_dep)
app.include_router(settings_router,     dependencies=_auth_dep)
app.include_router(search_router,       dependencies=_auth_dep)
app.include_router(stats_router,        dependencies=_auth_dep)
app.include_router(kline_router,        dependencies=_auth_dep)


@app.on_event("startup")
def on_startup():
    init_db()
    import threading
    def _warmup():
        try:
            from server.routers.search import _load_securities
            _load_securities()
        except Exception:
            pass
    threading.Thread(target=_warmup, daemon=True).start()


# Serve React build in production (web/dist must exist)
_dist = Path(__file__).parent.parent / "web" / "dist"
if _dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
```

- [ ] **Step 4: 运行全部认证测试**

```bash
pytest tests/test_auth.py -v
```

预期：全部 `PASSED`

- [ ] **Step 5: 修复 kline 测试：添加 auth 依赖 override**

kline 路由现在受保护，`test_kline_router.py` 的测试会返回 401。使用 FastAPI dependency override 绕过 auth（不需要真实 token 或 DB）。

在 `tests/test_kline_router.py` 的 `client = TestClient(app)` 这行**之前**插入：

```python
from server.auth import get_current_user
from server.models import User as _User

def _mock_auth():
    return _User(id=0, username="_test_", is_active=True, hashed_password="")

app.dependency_overrides[get_current_user] = _mock_auth
```

完整文件开头应如下（保留原有的 import 和 patch）：

```python
# tests/test_kline_router.py
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from server.main import app
from server.auth import get_current_user
from server.models import User as _User


def _mock_auth():
    return _User(id=0, username="_test_", is_active=True, hashed_password="")


app.dependency_overrides[get_current_user] = _mock_auth

client = TestClient(app)
# ... 其余内容不变
```

- [ ] **Step 6: 确认全部测试通过**

```bash
pytest tests/test_auth.py tests/test_kline_router.py -v
```

预期：全部 `PASSED`

- [ ] **Step 7: Commit**

```bash
git add server/main.py tests/test_auth.py tests/test_kline_router.py
git commit -m "feat(auth): register auth router and protect all API routes"
```

---

### Task 6: 用户管理脚本（manage_users.py）

**Files:**
- Create: `manage_users.py`

- [ ] **Step 1: 创建 `manage_users.py`**

```python
#!/usr/bin/env python3
"""CLI tool for managing TradingAgents users.

Usage:
  python manage_users.py add <username> <password>
  python manage_users.py list
  python manage_users.py delete <username>
  python manage_users.py reset-password <username> <new_password>
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# Trigger DB init so tables exist
from server.database import SessionLocal, engine, Base
from server import models as _models_module  # noqa: F401 — register all models


def _ensure_tables():
    Base.metadata.create_all(bind=engine)


def add_user(username: str, password: str) -> int:
    from server.models import User
    from server.auth import hash_password
    _ensure_tables()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            print(f"Error: user '{username}' already exists")
            return 1
        user = User(username=username, hashed_password=hash_password(password))
        db.add(user)
        db.commit()
        print(f"Created user '{username}'")
        return 0
    finally:
        db.close()


def list_users() -> int:
    from server.models import User
    _ensure_tables()
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at).all()
        if not users:
            print("No users found")
            return 0
        print(f"{'ID':<5} {'Username':<20} {'Active':<8} Created")
        print("-" * 55)
        for u in users:
            print(f"{u.id:<5} {u.username:<20} {'Yes' if u.is_active else 'No':<8} {u.created_at}")
        return 0
    finally:
        db.close()


def delete_user(username: str) -> int:
    from server.models import User
    _ensure_tables()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: user '{username}' not found")
            return 1
        db.delete(user)
        db.commit()
        print(f"Deleted user '{username}'")
        return 0
    finally:
        db.close()


def reset_password(username: str, new_password: str) -> int:
    from server.models import User
    from server.auth import hash_password
    _ensure_tables()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: user '{username}' not found")
            return 1
        user.hashed_password = hash_password(new_password)
        db.commit()
        print(f"Password reset for '{username}'")
        return 0
    finally:
        db.close()


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]
    if cmd == "add" and len(args) == 3:
        return add_user(args[1], args[2])
    if cmd == "list" and len(args) == 1:
        return list_users()
    if cmd == "delete" and len(args) == 2:
        return delete_user(args[1])
    if cmd == "reset-password" and len(args) == 3:
        return reset_password(args[1], args[2])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 手动测试脚本**

```bash
python manage_users.py add testadmin Test@12345
python manage_users.py list
python manage_users.py reset-password testadmin NewPass@999
python manage_users.py delete testadmin
python manage_users.py list
```

预期输出（依次）：
```
Created user 'testadmin'
ID    Username             Active   Created
---------------------------------------------------
1     testadmin            Yes      ...
Password reset for 'testadmin'
Deleted user 'testadmin'
No users found
```

- [ ] **Step 3: Commit**

```bash
git add manage_users.py
git commit -m "feat(auth): add manage_users.py CLI for user management"
```

---

### Task 7: 前端类型 + API 客户端

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/api/client.ts`

- [ ] **Step 1: 在 `web/src/types.ts` 末尾追加**

```typescript
export interface AuthToken {
  access_token: string
  token_type: string
}

export interface AuthUser {
  id: number
  username: string
  is_active: boolean
}
```

- [ ] **Step 2: 修改 `web/src/api/client.ts`**

将整个文件替换为：

```typescript
// web/src/api/client.ts
import axios from "axios"
import type {
  Analysis, AnalysisListResponse, ProgressEvent, Settings, SettingsUpdate,
  ModelsResponse, Provider, TestResult, AggregateStats, KLineResponse,
  AuthToken,
} from "../types"

const http = axios.create({ baseURL: "/api" })

// ── Request interceptor: inject Bearer token ──────────────────────────────────
http.interceptors.request.use((config) => {
  const token = localStorage.getItem("auth_token")
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ── Response interceptor: 401 → force re-login ────────────────────────────────
http.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && !err.config?.url?.includes("/auth/login")) {
      localStorage.removeItem("auth_token")
      localStorage.removeItem("auth_username")
      window.location.reload()
    }
    return Promise.reject(err)
  }
)

export const api = {
  // ── Auth ────────────────────────────────────────────────────────────────────
  login: (username: string, password: string) =>
    http.post<AuthToken>("/auth/login", { username, password }).then((r) => r.data),

  // ── Analyses ────────────────────────────────────────────────────────────────
  createAnalysis: (payload: {
    ticker: string
    trade_date: string
    analysts: string[]
    depth: number
  }) => http.post<Analysis>("/analyses", payload).then((r) => r.data),

  listAnalyses: (skip = 0, limit = 50) =>
    http
      .get<AnalysisListResponse>("/analyses", { params: { skip, limit } })
      .then((r) => r.data),

  getAnalysis: (id: string) =>
    http.get<Analysis>(`/analyses/${id}`).then((r) => r.data),

  deleteAnalysis: (id: string) => http.delete(`/analyses/${id}`),
  stopAnalysis: (id: string) => http.post(`/analyses/${id}/stop`),

  getNotificationCount: () =>
    http
      .get<{ unseen: number }>("/notifications/count")
      .then((r) => r.data),

  markAllRead: () => http.post("/notifications/read"),

  getSettings: () => http.get<Settings>("/settings").then((r) => r.data),
  saveSettings: (payload: SettingsUpdate) =>
    http.post<Settings>("/settings", payload).then((r) => r.data),
  getModels: (provider: string) =>
    http.get<ModelsResponse>("/settings/models", { params: { provider } }).then((r) => r.data),
  getProviders: () => http.get<Provider[]>("/settings/providers").then((r) => r.data),
  testConnection: () => http.post<TestResult>("/settings/test").then((r) => r.data),
  getFutuStatus: () =>
    http.get<{ connected: boolean; error?: string }>("/settings/futu-status").then((r) => r.data),
  getJQStatus: () =>
    http.get<{ connected: boolean; username?: string; queries_remaining?: number; error?: string }>(
      "/settings/jq-status"
    ).then((r) => r.data),

  getAggregateStats: () =>
    http.get<AggregateStats>("/stats").then((r) => r.data),

  searchStocks: (q: string) =>
    http
      .get<{ ticker: string; name: string; code: string; market: string }[]>(
        "/search",
        { params: { q, limit: 10 } }
      )
      .then((r) => r.data),

  getKLine: (ticker: string, time_range = "1Y", signal?: AbortSignal) =>
    http
      .get<KLineResponse>(`/kline/${encodeURIComponent(ticker)}`, { params: { time_range }, signal })
      .then((r) => r.data),
}

export function openProgressStream(
  analysisId: string,
  onEvent: (event: ProgressEvent) => void,
  onDone: () => void
): EventSource {
  const token = localStorage.getItem("auth_token")
  const url = `/api/analyses/${analysisId}/stream${token ? `?token=${encodeURIComponent(token)}` : ""}`
  const es = new EventSource(url)
  es.onmessage = (e) => {
    const data = JSON.parse(e.data) as ProgressEvent
    onEvent(data)
    if (data.status === "complete" || data.status === "failed" || data.error) {
      es.close()
      onDone()
    }
  }
  es.onerror = () => {
    es.close()
    onDone()
  }
  return es
}
```

> **注意 EventSource：** 浏览器原生 `EventSource` 不支持自定义 header，无法通过 `Authorization` header 传 token。上面的方案改为通过 query string `?token=...` 传递。服务端 `get_current_user` 在 Task 8 中会同时支持 Bearer header 和 `?token=` 参数。

- [ ] **Step 3: 确认 TypeScript 编译无报错**

```bash
cd web && npx tsc --noEmit
```

预期：无报错（0 errors）

- [ ] **Step 4: Commit**

```bash
git add web/src/types.ts web/src/api/client.ts
git commit -m "feat(auth): add auth types and axios interceptors for JWT"
```

---

### Task 8: SSE 流端点支持 token query 参数

**Files:**
- Modify: `server/routers/analyses.py`（stream 端点额外接受 query token）

EventSource 不支持自定义 header，所以 `/stream` 端点需要额外接受 `?token=` 参数。

- [ ] **Step 1: 查看现有 stream 端点**

打开 `server/routers/analyses.py`，找到 stream 端点（通常是 `GET /{id}/stream`）。

- [ ] **Step 2: 修改 stream 端点，支持 query token 认证**

找到类似这样的端点：
```python
@router.get("/{id}/stream")
def stream_analysis(id: str, db: Session = Depends(get_db)):
```

修改为：

```python
from fastapi import Query
from server.auth import decode_token

@router.get("/{id}/stream")
def stream_analysis(
    id: str,
    db: Session = Depends(get_db),
    token: str = Query(default=""),
):
    # Validate token from query string (EventSource can't send headers)
    username = decode_token(token)
    if not username:
        from fastapi.responses import Response
        return Response(status_code=401)
    # ... 原有的 stream 逻辑不变
```

> 注：这个端点已经通过 `app.include_router(analyses_router, dependencies=[Depends(get_current_user)])` 保护了 Bearer header 路径。但 EventSource 走 query token，不走 Bearer header，所以需要在端点内部额外验证 query token，同时移除对这个端点的全局 auth dep（见注意事项）。

实际上，更简单的做法：不修改 stream 端点，直接在全局 auth dep 里同时支持 query token。修改 `server/auth.py` 的 `get_current_user`，改为从 header **或** query 参数取 token：

```python
from fastapi import Request

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):
    from server.models import User
    # Try Authorization header first, then ?token= query param
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.query_params.get("token", "")

    username = decode_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
```

同时从 `server/auth.py` 删除 `oauth2_scheme` 的导入和变量（改用 `Request`，不再需要 `OAuth2PasswordBearer`）。

- [ ] **Step 3: 更新 `server/auth.py`（移除 OAuth2PasswordBearer）**

将 `server/auth.py` 中的 `get_current_user` 替换为使用 `Request` 的版本（完整文件）：

```python
# server/auth.py
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from server.database import get_db

_SECRET_KEY = os.environ.get("JWT_SECRET", "dev-only-secret-change-in-production")
_ALGORITHM = "HS256"
_EXPIRE_HOURS = 24

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": expire}, _SECRET_KEY, algorithm=_ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    """Return username from token, or None if invalid or expired."""
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):
    """FastAPI dependency: extract JWT from Authorization header or ?token= query param."""
    from server.models import User  # late import avoids circular dependency
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.query_params.get("token", "")

    username = decode_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
```

- [ ] **Step 4: 同步更新 `server/routers/auth.py`（移除 oauth2_scheme 依赖）**

`/api/auth/me` 端点已经用 `Depends(get_current_user)` 而 `get_current_user` 现在用 `Request`，无需额外改动。检查 auth.py 不再导出 `oauth2_scheme`。

- [ ] **Step 5: 运行全部测试**

```bash
pytest tests/test_auth.py tests/test_kline_router.py -v
```

注意：`test_me_without_token` 测试需要验证 401 仍然返回。由于 `get_current_user` 现在读 `Request`，不再通过 `OAuth2PasswordBearer` 注入，测试应该仍然通过（空 token → decode_token 返回 None → 401）。

预期：全部 `PASSED`

- [ ] **Step 6: Commit**

```bash
git add server/auth.py
git commit -m "feat(auth): support ?token= query param in get_current_user for EventSource SSE"
```

---

### Task 9: AuthContext

**Files:**
- Create: `web/src/context/AuthContext.tsx`

- [ ] **Step 1: 创建 `web/src/context/AuthContext.tsx`**

```tsx
// web/src/context/AuthContext.tsx
import { createContext, useContext, useState, useCallback, type ReactNode } from "react"
import { api } from "../api/client"

interface AuthContextValue {
  token: string | null
  username: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem("auth_token")
  )
  const [username, setUsername] = useState<string | null>(() =>
    localStorage.getItem("auth_username")
  )

  const login = useCallback(async (uname: string, password: string) => {
    const resp = await api.login(uname, password)  // throws on 401
    localStorage.setItem("auth_token", resp.access_token)
    localStorage.setItem("auth_username", uname)
    setToken(resp.access_token)
    setUsername(uname)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem("auth_token")
    localStorage.removeItem("auth_username")
    setToken(null)
    setUsername(null)
  }, [])

  return (
    <AuthContext.Provider value={{ token, username, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
```

- [ ] **Step 2: 确认 TypeScript 编译无报错**

```bash
cd web && npx tsc --noEmit
```

预期：无报错

- [ ] **Step 3: Commit**

```bash
git add web/src/context/AuthContext.tsx
git commit -m "feat(auth): add AuthContext with token persistence and login/logout"
```

---

### Task 10: LoginPage

**Files:**
- Create: `web/src/pages/LoginPage.tsx`

- [ ] **Step 1: 创建 `web/src/pages/LoginPage.tsx`**

```tsx
// web/src/pages/LoginPage.tsx
import { useState, type FormEvent } from "react"
import { useAuth } from "../context/AuthContext"

export default function LoginPage() {
  const { login } = useAuth()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(username, password)
    } catch {
      setError("用户名或密码错误")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center">
      <div className="bg-surface border border-border rounded-lg p-8 w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="w-12 h-12 rounded bg-accent/20 flex items-center justify-center text-accent font-bold text-xl mx-auto mb-3">
            TA
          </div>
          <h1 className="text-text text-xl font-semibold">TradingAgents</h1>
          <p className="text-gray-400 text-sm mt-1">请登录以继续</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-300 mb-1">用户名</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-bg border border-border rounded px-3 py-2 text-text text-sm focus:outline-none focus:border-accent"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm text-gray-300 mb-1">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-bg border border-border rounded px-3 py-2 text-text text-sm focus:outline-none focus:border-accent"
              required
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-accent text-white rounded py-2 text-sm font-medium hover:bg-accent/90 disabled:opacity-50 transition-colors"
          >
            {loading ? "登录中…" : "登录"}
          </button>
        </form>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/pages/LoginPage.tsx
git commit -m "feat(auth): add LoginPage component"
```

---

### Task 11: 更新 App.tsx + Sidebar 退出按钮

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/components/Sidebar.tsx`

- [ ] **Step 1: 修改 `web/src/App.tsx`**

将整个文件替换为：

```tsx
// web/src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { AuthProvider, useAuth } from "./context/AuthContext"
import Sidebar from "./components/Sidebar"
import LoginPage from "./pages/LoginPage"
import NewAnalysis from "./pages/NewAnalysis"
import History from "./pages/History"
import Report from "./pages/Report"
import SettingsPage from "./pages/Settings"
import StatsPage from "./pages/StatsPage"

function AppShell() {
  const { token } = useAuth()

  if (!token) return <LoginPage />

  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden bg-bg">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Navigate to="/new" replace />} />
            <Route path="/new" element={<NewAnalysis />} />
            <Route path="/history" element={<History />} />
            <Route path="/report/:id" element={<Report />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/stats" element={<StatsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  )
}
```

- [ ] **Step 2: 修改 `web/src/components/Sidebar.tsx`**

在文件顶部添加 `useAuth` import，并在 sidebar 底部追加退出按钮。将整个文件替换为：

```tsx
// web/src/components/Sidebar.tsx
import { useEffect, useState } from "react"
import { NavLink, useNavigate } from "react-router-dom"
import { api } from "../api/client"
import { useAuth } from "../context/AuthContext"

const NAV = [
  { to: "/new",      icon: "＋",  label: "新建分析" },
  { to: "/history",  icon: "📋",  label: "历史报告" },
  { to: "/stats",    icon: "📊",  label: "用量统计" },
  { to: "/settings", icon: "⚙️", label: "设置" },
]

export default function Sidebar() {
  const [unseen, setUnseen] = useState(0)
  const navigate = useNavigate()
  const { logout, username } = useAuth()

  useEffect(() => {
    const refresh = () =>
      api.getNotificationCount().then((r) => setUnseen(r.unseen))
    refresh()
    const id = setInterval(refresh, 10_000)
    return () => clearInterval(id)
  }, [])

  const handleHistoryClick = async () => {
    if (unseen > 0) await api.markAllRead()
    setUnseen(0)
    navigate("/history")
  }

  return (
    <aside className="w-14 bg-surface border-r border-border flex flex-col items-center py-4 gap-6 shrink-0">
      <div className="w-8 h-8 rounded bg-accent/20 flex items-center justify-center text-accent font-bold text-sm">
        TA
      </div>
      {NAV.map((item) =>
        item.to === "/history" ? (
          <button
            key={item.to}
            onClick={handleHistoryClick}
            className="relative w-10 h-10 flex items-center justify-center rounded hover:bg-accent/10 text-gray-400 hover:text-accent transition-colors text-lg"
            title={item.label}
          >
            {item.icon}
            {unseen > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[9px] rounded-full w-4 h-4 flex items-center justify-center">
                {unseen > 9 ? "9+" : unseen}
              </span>
            )}
          </button>
        ) : (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `w-10 h-10 flex items-center justify-center rounded hover:bg-accent/10 transition-colors text-lg ${
                isActive
                  ? "text-accent bg-accent/10"
                  : "text-gray-400 hover:text-accent"
              }`
            }
            title={item.label}
          >
            {item.icon}
          </NavLink>
        )
      )}

      {/* 退出按钮，固定在底部 */}
      <div className="mt-auto">
        <button
          onClick={logout}
          className="w-10 h-10 flex items-center justify-center rounded hover:bg-red-500/10 text-gray-400 hover:text-red-400 transition-colors text-lg"
          title={`退出 (${username ?? ""})`}
        >
          ⏏
        </button>
      </div>
    </aside>
  )
}
```

- [ ] **Step 3: 确认 TypeScript 编译无报错**

```bash
cd web && npx tsc --noEmit
```

预期：无报错

- [ ] **Step 4: 启动开发服务器，手动验证功能**

```bash
# 终端 1：后端
JWT_SECRET=dev-test-secret uvicorn server.main:app --reload --port 8000

# 终端 2：前端
cd web && npm run dev
```

在 `http://localhost:5173` 验证：
- [ ] 打开页面，显示登录界面，不显示主应用
- [ ] 输入错误密码，显示"用户名或密码错误"提示
- [ ] 先创建用户：`python manage_users.py add admin Admin@123`
- [ ] 用正确密码登录，跳转到主界面
- [ ] 刷新页面，仍保持登录状态（localStorage token 持久化）
- [ ] 点击 ⏏ 退出按钮，返回登录页面
- [ ] 退出后手动访问 `http://localhost:5173/new`，仍显示登录页（不跳过）

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/components/Sidebar.tsx
git commit -m "feat(auth): integrate AuthContext into App and Sidebar with logout button"
```

---

## 自检：Spec 覆盖确认

| Spec 需求 | 对应 Task |
|-----------|-----------|
| POST /api/auth/login | Task 4 |
| GET /api/auth/me | Task 4 |
| JWT HS256, 24h 有效期 | Task 3 |
| JWT_SECRET 从环境变量读取 | Task 3（`_SECRET_KEY = os.environ.get("JWT_SECRET", ...)`）|
| 所有 /api/* 路由保护 | Task 5 |
| /api/auth/login 不受保护 | Task 5（auth_router 单独注册，无 dependency）|
| bcrypt 密码哈希 | Task 3 |
| User 表 MySQL/SQLite | Task 2 |
| AuthContext（login/logout/token）| Task 9 |
| LoginPage | Task 10 |
| axios Bearer header 注入 | Task 7 |
| 401 → 强制重登录 | Task 7 |
| EventSource SSE token 支持 | Task 8 |
| 退出按钮（Sidebar）| Task 11 |
| manage_users.py add/list/delete/reset-password | Task 6 |
