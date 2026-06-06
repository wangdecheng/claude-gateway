# Backend: Authentication System

## 涉及文件

| 职责 | 文件 |
|------|------|
| JWT 依赖 (cookie) | `backend/app/dependencies.py` |
| API Key 依赖 (Bearer header) | `backend/api/dependencies.py` |
| Auth 路由 | `backend/app/routers/auth.py` |
| Auth 业务逻辑 | `backend/app/services/auth_service.py` |
| API Key 路由 | `backend/app/routers/api_keys.py` |
| API Key 业务逻辑 | `backend/app/services/api_key_service.py` |
| User ORM | `backend/app/models/user.py` |
| ApiKey ORM | `backend/app/models/api_key.py` |
| Auth schemas | `backend/app/schemas/auth.py`, `backend/app/schemas/api_key.py` |

## 双轨认证体系

```
┌─────────────────────────────────────────────────────────┐
│                   认证入口                               │
├────────────────────────┬────────────────────────────────┤
│  JWT Cookie            │  API Key (Bearer)              │
│  用途: 前端管理界面     │  用途: API 代理调用            │
│  传输: HttpOnly cookie  │  传输: Authorization header    │
│  Cookie名: high_api_   │  Key格式: sk-<40 hex chars>    │
│           session      │  存储: bcrypt hash + prefix    │
│  验证: JWT decode      │  验证: bcrypt verify           │
│  时效: 24h 可配置      │  时效: 永久 (revoke 控制)      │
└────────────────────────┴────────────────────────────────┘
```

## JWT Cookie 认证链路

### 注册
```
POST /api/auth/register { email, password }
  → 校验 email 唯一性
  → bcrypt(password) → password_hash
  → INSERT user (balance=0, role="user", status="active")
  → generate_jwt(user_id, email, role, 24h)
  → Set-Cookie: high_api_session=<jwt>; HttpOnly; SameSite=Lax
```

### 登录
```
POST /api/auth/login { email, password }
  → 查 user by email
  → bcrypt.verify(password, user.password_hash)
  → 检查 user.status == "active"
  → generate_jwt → Set-Cookie
```

### 鉴权依赖: get_current_user
```python
def get_current_user(request, db) -> User:
    token = request.cookies["high_api_session"]
    payload = decode_jwt(token)  # HS256, JWT_SECRET
    user = db.get(User, payload["sub"])
    if user.status != "active": raise 403
    return user
```

### 管理员鉴权: get_current_admin
```python
def get_current_admin(current_user = get_current_user) -> User:
    if current_user.role != "admin": raise 403
    return current_user
```

### JWT 配置
- 算法: HS256
- 密钥: `JWT_SECRET` env (默认 `dev-secret-change-in-production`)
- 过期: `JWT_EXPIRE_SECONDS` (默认 86400 = 24h)
- Payload: `{ sub: user_id, email, role, exp, iat }`

## API Key 认证链路

### 创建 Key
```
POST /api/keys { name }
  → generate_key(): "sk-" + secrets.token_hex(20)  # sk-<40位hex>
  → hash_key(): bcrypt(full_key)
  → INSERT api_key (user_id, key_prefix[:10], key_hash, status="active")
  → 返回完整 key (仅此一次!)
```

### 鉴权依赖: require_api_key
```python
def require_api_key(request, db) -> (User, ApiKey):
    token = request.headers["Authorization"]
    token = token.removeprefix("Bearer ")
    # 也支持 x-api-key header
    candidates = db.query(ApiKey).filter(
        ApiKey.key_prefix == token[:10],
        ApiKey.status == "active"
    )
    for key in candidates:
        if bcrypt.verify(token, key.key_hash):
            return (key.user, key)
    raise 401
```

### Key 安全
- 完整 key 只返回一次（创建时）
- DB 只存 bcrypt hash + 前 10 位前缀
- 前缀用于缩小查找范围，bcrypt 做最终验证
- Revoke 不删除记录，仅设 status="revoked"（审计追溯）

## 密码管理

### 密码哈希
- bcrypt (via `bcrypt` lib)
- `hash_password(plain)` → hash
- `verify_password(plain, hash)` → bool

### 密码重置
```
POST /api/auth/forgot-password { email }
  → 查 user
  → generate_reset_token(email): JWT(purpose="password_reset", exp=15min)
  → 返回 token (当前 dev 模式，生产应发邮件)

POST /api/auth/reset-password { token, new_password }
  → decode_reset_token(token): 验证 purpose + 过期
  → hash_password(new_password)
  → UPDATE user.password_hash
```

## 前端中间件

`frontend/middleware.ts` 独立实现 JWT 验证（使用 `jose` 库），不依赖后端:
- 公开路径: `/login`, `/register`, `/forgot-password`, `/reset-password` — 已登录则重定向
- 受保护路径: 验证 `high_api_session` cookie → JWT decode
- Admin 路径: 额外检查 `payload.role === "admin"`
- 注入 `X-User-ID`, `X-User-Role` request headers

## 常见开发场景

### 添加 OAuth 登录
1. `auth_service.py`: 添加 OAuth token 验证 + 账号关联逻辑
2. `auth.py` (router): 添加 `/auth/oauth/{provider}` 路由
3. `user.py` (model): 可能需要 `oauth_provider`, `oauth_id` 字段
4. `frontend`: 添加 OAuth 按钮组件

### 修改权限模型
1. `user.py`: 修改 `role` 字段 (enum → 新角色)
2. `dependencies.py`: 添加新的 Depends 函数 (如 `get_current_operator`)
3. `middleware.ts`: 前端权限检查逻辑
