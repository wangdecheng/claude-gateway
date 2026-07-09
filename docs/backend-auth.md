# Backend: Authentication System

## 涉及文件

| 职责 | 文件 |
|------|------|
| JWT 依赖 (cookie) | `backend/app/dependencies.py` (`get_current_user`, `get_current_admin`) |
| API Key 依赖 (Bearer header) | `backend/app/dependencies.py` (`get_current_user_from_api_key`) + `backend/api/dependencies.py` (`require_api_key`) |
| Auth 路由 | `backend/app/routers/auth.py` |
| Auth 业务逻辑 | `backend/app/services/auth_service.py` |
| API Key 路由 | `backend/app/routers/api_keys.py` |
| API Key 业务逻辑 | `backend/app/services/api_key_service.py` |
| User ORM | `backend/app/models/user.py` |
| ApiKey ORM | `backend/app/models/api_key.py` |
| Auth schemas | `backend/app/schemas/auth.py`, `backend/app/schemas/api_key.py` |
| JWT 配置 | `backend/config/settings.py` (`jwt_private_key`, `jwt_public_key`, `jwt_algorithm`) |

## 双轨认证体系

```
┌─────────────────────────────────────────────────────────┐
│                   认证入口                               │
├────────────────────────┬────────────────────────────────┤
│  JWT Cookie            │  API Key (Bearer)              │
│  用途: 前端管理界面     │  用途: API 代理 (/v1/* 调用)   │
│  传输: HttpOnly cookie  │  传输: Authorization header    │
│  Cookie名: high_api_   │  Key格式: sk-<40 hex> (共43字符)│
│           session      │  存储: bcrypt hash + prefix    │
│  验签: RS256 公钥       │  验证: bcrypt verify           │
│  时效: 24h 可配置      │  时效: 永久 (revoke 控制)      │
└────────────────────────┴────────────────────────────────┘
```

## JWT Cookie 认证链路

> ⚠️ **算法是 RS256（非对称）**，不是 HS256。后端用 `jwt_private_key` 签发，前端 middleware 用 `jwt_public_key` 验签。公钥泄露也无法伪造 token。

### 注册 / 登录
```
POST /api/auth/register | /api/auth/login { email, password }
  -> register()/login() in auth_service
  -> bcrypt(password) -> password_hash
  -> INSERT user (balance=0, role="user", status="active")   # register only
  -> generate_jwt(user.id, user.role)
       payload = { user_id, role, exp }   # 注意: 无 sub/email/iat
       sign with jwt_private_key (RS256)
  -> JSONResponse + _set_auth_cookie(token)
  -> 返回 { user_id, email, balance, role }   # snake_case
```

### Cookie 属性 (`_set_auth_cookie`)
```
key="high_api_session", httponly=True, secure=False (dev),
samesite="lax", max_age=86400
```
> 生产环境需 `secure=True`（当前硬编码 False）。

### 鉴权依赖: `get_current_user`
```python
async def get_current_user(request, db) -> User:
    token = request.cookies.get("high_api_session")
    if not token: raise 401 UNAUTHORIZED
    payload = decode_jwt(token)           # RS256 verify with jwt_public_key
    user_id = payload.get("user_id")       # 注意: 用 user_id 不是 sub
    user = db.get(User, user_id)
    if user.status != "active": raise 403 USER_DISABLED
    return user
```

### 管理员鉴权: `get_current_admin`
```python
async def get_current_admin(request, db) -> User:
    user = await get_current_user(request, db)
    if user.role != "admin": raise 403 FORBIDDEN
    return user
```

### JWT 配置 (`config/settings.py`)
| 字段 | 默认 | 说明 |
|------|------|------|
| `jwt_algorithm` | `"RS256"` | 签名算法 |
| `jwt_private_key` | `""` | 后端签发用私钥（PEM） |
| `jwt_public_key` | `""` | 验签用公钥（PEM），前端同款 base64 注入 |
| `jwt_expire_seconds` | `86400` (24h) | token 有效期 |

> 前端 `middleware.ts` 从 `JWT_PUBLIC_KEY` 环境变量读取 base64 公钥并 decode 回 PEM（避开 systemd EnvironmentFile 对 `\` 的转义）。

### `/me` 端点
```
GET /api/auth/me  (需 cookie)
  -> get_current_user -> 返回 { user_id, email, balance, role }  # snake_case
```

## API Key 认证链路

### 创建 Key (`api_key_service.generate_key`)
```python
raw_key   = "sk-" + secrets.token_hex(20)   # "sk-" + 40 hex = 43 字符
key_prefix = raw_key[:10]                    # "sk-a1b2c3d" (sk- + 前 7 hex)，用于快速查找
key_hash   = bcrypt(raw_key)
INSERT api_key (user_id, name, key_prefix, key_hash, status="active", channel_id)
返回完整 raw_key (仅此一次!)
```
> 创建时可绑定 `channel_id`（-> providers.id），NULL 表示旧式自动路由。

### 鉴权依赖: `get_current_user_from_api_key` / `require_api_key`
```python
async def get_current_user_from_api_key(request, db) -> (User, ApiKey):
    auth_header = request.headers.get("Authorization", "")
    # 仅支持 Bearer，不支持 x-api-key
    raw_key = auth_header[7:]   # 去掉 "Bearer "
    if not raw_key.startswith("sk-") or len(raw_key) < 20: raise 401 INVALID_FORMAT

    key_prefix = raw_key[:10]
    candidates = SELECT api_key WHERE key_prefix=? AND status="active"
    for candidate in candidates:
        if bcrypt.checkpw(raw_key, candidate.key_hash):
            matched = candidate; break
    if not matched: raise 401 INVALID_API_KEY

    user = SELECT user WHERE id=matched.user_id
    if user.status != "active": raise 401 USER_NOT_FOUND

    matched.last_used_at = now()   # 更新最后使用时间
    return (user, matched)
```

### Key 安全
- 完整 key 只返回一次（创建时）
- DB 只存 bcrypt hash + 前 10 字符前缀
- 前缀缩小查找范围，bcrypt 做最终验证
- Revoke 不删除记录，仅设 `status="revoked"`（审计追溯）

## 密码管理

### 密码哈希
- bcrypt (`bcrypt` lib)
- `hash_password(plain)` -> hash
- `verify_password(plain, hash)` -> bool

### 密码重置（RS256 JWT，15min）
```
POST /api/auth/forgot-password { email }
  -> forgot_password(email): 查 user；存在则 generate_reset_token(user_id)
       payload = { user_id, purpose="password_reset", exp=now+15min }
       sign with jwt_private_key (RS256)
  -> 始终返回 200（防 email 枚举）；dev 模式返回 token 便于测试

POST /api/auth/reset-password { token, new_password }
  -> decode_reset_token(token): RS256 验签 + 检查 purpose + 过期
  -> hash_password(new_password) -> UPDATE user.password_hash

POST /api/auth/change-password { current_password, new_password }  (需登录)
  -> verify_password(current, hash) -> 失败抛 WRONG_PASSWORD
  -> hash_password(new_password) -> UPDATE
```

## 前端中间件 (`frontend/middleware.ts`)

独立用 `jose` 库做 **RS256 签名验签**（不依赖后端）：
- 公钥从 `JWT_PUBLIC_KEY`（base64）解码为 PEM
- `jwtVerify(token, publicKey, { algorithms: ["RS256"] })` —— 验签，非仅 decode
- 公开路径 (`/login` `/register` `/forgot-password` `/reset-password`): 已登录则按 role 重定向（admin -> `/admin`，user -> `/`）
- 受保护路径: 无 cookie 或验签失败 -> 重定向 `/login` 并删 cookie
- Admin 路径: `payload.role !== "admin"` -> 返回 **403 JSON**（`{ error: "无权访问" }`），非重定向
- 注入 `X-User-ID`, `X-User-Role` 请求头给后端

## 常见开发场景

### 添加 OAuth 登录
1. `auth_service.py`: 添加 OAuth token 验证 + 账号关联逻辑
2. `auth.py` (router): 添加 `/api/auth/oauth/{provider}` 路由
3. `user.py` (model): 可能需要 `oauth_provider`, `oauth_id` 字段
4. `frontend`: 添加 OAuth 按钮组件

### 修改权限模型
1. `user.py`: 修改 `role` 字段 (enum -> 新角色)
2. `dependencies.py`: 添加新的 Depends 函数 (如 `get_current_operator`)
3. `middleware.ts`: 前端权限检查逻辑

### 轮换 JWT 密钥
1. 生成新 RS256 密钥对
2. `~/.fcc/.env` 更新 `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY`（base64）
3. 重启后端 + 前端（前端 middleware 启动时读公钥）
4. 旧 token 验签失败 -> 用户重登录
