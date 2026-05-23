# Auth System Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 TradingAgents Web UI 增加 JWT 用户认证，保护所有 `/api/*` 路由，并提供登录页面和用户管理脚本。

**Architecture:** FastAPI 后端通过 `/api/auth/login` 签发 JWT Token，前端将 Token 存入 localStorage 并随每个请求携带。所有 API 路由通过 FastAPI Depends 注入 `get_current_user` 依赖实现保护。用户存储在 MySQL `users` 表，密码用 bcrypt 哈希。

**Tech Stack:** `python-jose[cryptography]`、`passlib[bcrypt]`、React Context API、axios interceptor

---

## 范围说明

本 spec 仅涵盖认证系统。MySQL 迁移和服务器部署见 `2026-05-23-deployment-design.md`。

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `server/auth.py` | JWT 工具函数 + `get_current_user` FastAPI 依赖 |
| `server/routers/auth.py` | `/api/auth/login` 和 `/api/auth/me` 端点 |
| `manage_users.py` | 命令行用户管理脚本（add/list/delete） |
| `web/src/context/AuthContext.tsx` | React auth 状态（token、user、login、logout） |
| `web/src/pages/LoginPage.tsx` | 登录表单页 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `server/models.py` | 新增 `User` SQLAlchemy 模型 |
| `server/main.py` | 注册 auth router；CORS 加 `Authorization` header |
| `server/routers/analyses.py` | 所有端点加 `get_current_user` 依赖 |
| `server/routers/settings.py` | 同上 |
| `server/routers/search.py` | 同上 |
| `server/routers/stats.py` | 同上 |
| `server/routers/notifications.py` | 同上 |
| `server/routers/kline.py` | 同上 |
| `web/src/api/client.ts` | axios 请求拦截器（加 Bearer token）+ 响应拦截器（401 → 跳登录） |
| `web/src/App.tsx` | 用 `AuthProvider` 包裹；未登录时渲染 `<LoginPage />` |
| `pyproject.toml` | 新增依赖：`python-jose[cryptography]`、`passlib[bcrypt]` |

---

## 数据模型

### User 表（MySQL）

```python
class User(Base):
    __tablename__ = "users"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    username       = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active      = Column(Boolean, default=True, nullable=False)
    created_at     = Column(DateTime, default=datetime.utcnow)
```

---

## API 设计

### POST /api/auth/login

请求体：
```json
{ "username": "alice", "password": "secret" }
```

成功响应（200）：
```json
{ "access_token": "<jwt>", "token_type": "bearer" }
```

失败响应（401）：
```json
{ "detail": "用户名或密码错误" }
```

### GET /api/auth/me

需要 Bearer token，返回当前用户信息：
```json
{ "id": 1, "username": "alice", "is_active": true }
```

---

## JWT 规格

- 算法：HS256
- 有效期：24 小时
- Payload：`{ "sub": "<username>", "exp": <timestamp> }`
- 密钥：从环境变量 `JWT_SECRET` 读取（部署时必须设置，长度 ≥ 32 字符）

---

## 前端设计

### AuthContext

```tsx
interface AuthContextValue {
  token: string | null
  username: string | null
  login: (username: string, password: string) => Promise<void>  // 抛出 Error 表示失败
  logout: () => void
}
```

- `token` 初始从 `localStorage.getItem("auth_token")` 读取
- `login()` 调用 `POST /api/auth/login`，成功后存 token 到 localStorage
- `logout()` 清除 localStorage，重置 state

### 路由保护（App.tsx）

```tsx
// 未登录时整个 App 替换为登录页
const { token } = useAuth()
if (!token) return <LoginPage />
```

### axios 拦截器（client.ts）

```typescript
// 请求：自动加 Authorization header
http.interceptors.request.use(config => {
  const token = localStorage.getItem("auth_token")
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应：401 自动清除 token（触发重渲染 → 登录页）
http.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem("auth_token")
      window.location.reload()
    }
    return Promise.reject(err)
  }
)
```

### 登录页（LoginPage.tsx）

- 用户名 + 密码输入框
- 提交时调用 `AuthContext.login()`
- 失败显示错误提示（中文："用户名或密码错误"）
- 成功后 AuthContext 更新 token，App.tsx 自动渲染主界面

### 退出登录

在 `web/src/components/Sidebar.tsx` 底部加退出按钮，调用 `AuthContext.logout()`。

---

## 用户管理脚本（manage_users.py）

```
python manage_users.py add <username> <password>   # 新增用户
python manage_users.py list                         # 列出所有用户
python manage_users.py delete <username>            # 删除用户
python manage_users.py reset-password <username> <new_password>
```

从 `DATABASE_URL` 环境变量连接数据库，管理员 SSH 到服务器使用。

---

## 安全考量

- `JWT_SECRET` 必须通过环境变量注入，不得硬编码或提交到 git
- 密码用 `passlib.context.CryptContext(schemes=["bcrypt"])` 哈希，不可逆
- Token 不存服务端，服务端重启不影响已登录用户（24小时内）
- 前端 axios 拦截器在 401 时强制重新登录，防止 token 过期后静默失败
- `/api/auth/login` 本身不需要认证（公开端点）

---

## 不在本 spec 范围内

- 用户注册（固定用户，手动添加）
- 权限/角色系统（所有用户权限相同）
- 密码找回（SSH 执行 reset-password 脚本）
- Refresh Token（24小时重登录即可）
- HTTPS（见 deployment spec）
