# 部署与推送（`bin/deploy.sh`）

把代码改完推到 47.103.206.6 并重启服务的脚本：`bin/deploy.sh`。
**只同步代码**，不碰数据库（数据库配置的同步见下文 §5）。

---

## 1. 快速开始

```bash
# 1) 克隆仓库
git clone <repo> && cd claude-gateway

# 2) 放好 SSH 密钥（详见 §2）
mkdir -p ~/ai
cp /path/to/aliyun-ai01.pem ~/ai/aliyun-ai01.pem
chmod 600 ~/ai/aliyun-ai01.pem

# 3) 写代码 → commit → 跑脚本
bin/deploy.sh
```

默认情况下脚本会：

1. `rsync` 本地 `backend/` + `frontend/` 到远端 `/opt/cloude-gateway/{backend,frontend}/`
2. 远端跑 `uv sync`（Python 依赖同步）
3. 远端跑 `alembic upgrade head`（数据库迁移）
4. 远端跑 `npm ci` + `next build`（前端依赖 + 重新构建）
5. `systemctl restart cloude-backend` + `cloude-frontend`
6. 打 `/api/health` + `/` 做健康检查

---

## 2. SSH 密钥放置

脚本默认读 `$HOME/ai/aliyun-ai01.pem`（即 `~/ai/aliyun-ai01.pem`），文件名固定、路径可通过环境变量覆盖。

```bash
# 推荐位置（mac/linux）
mkdir -p ~/ai
cp /path/to/your-key.pem ~/ai/aliyun-ai01.pem
chmod 600 ~/ai/aliyun-ai01.pem
```

> 路径里**只放密钥文件本身**，不要把整个 `.pem` 目录加进仓库或备份。

如果换路径或换名字，三种方式任选其一：

```bash
# 方式 A：每次执行前 export
export DEPLOY_SSH_KEY=~/.ssh/cloude-prod.pem
bin/deploy.sh

# 方式 B：当次命令前 inline
DEPLOY_SSH_KEY=~/keys/aliyun-ai01.pem bin/deploy.sh

# 方式 C：写到 ~/.zshrc / ~/.bashrc 里持久化
echo 'export DEPLOY_SSH_KEY=~/ai/aliyun-ai01.pem' >> ~/.zshrc
```

> **不要把密钥 commit 进仓库。** `bin/deploy.sh` 默认会从 `$HOME` 读，不在仓库里。`docs/`、`*.md`、`*.sh` 都不应包含密钥内容。

---

## 3. 在新机器上第一次开发

### 3.1 必备工具

| 工具 | 用途 | 安装 |
|---|---|---|
| `git` | 拉仓库 | `brew install git` / 系统自带 |
| `rsync` | 同步文件到远端 | `brew install rsync`（mac 自带） |
| `ssh` | 连远端 | 系统自带 |
| `uv` | 本地 Python 依赖（开发时跑后端） | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `node` ≥ 22 + `npm` | 本地前端（开发时跑前端） | `brew install node@22` / nvm |
| PostgreSQL 17 | 本地数据库（开发时用） | `docker run -d --name cloude-gateway-postgres ...`（见 README/CLAUDE.md） |

### 3.2 首次拉到本地后的最小运行

```bash
# 后端
cd backend && uv sync
cp .env.example .env
# （可选）把远端 .env 拷过来再改，本地默认走 dev-encryption-key 即可
DATABASE_URL='postgresql+asyncpg://high_api:high_api_dev@localhost:5432/high_api' \
  uv run uvicorn server:app --host 0.0.0.0 --port 8082 --reload

# 前端
cd ../frontend && npm install
cp .env.example .env.local
# NEXT_PUBLIC_API_URL 默认指向 localhost:8082 即可
npm run dev
```

### 3.3 跨机器须知

- **本机 `.env` ≠ 远端 `.env`**：本地永远用开发密钥（`UPSTREAM_KEY_ENCRYPTION_KEY` 留空 → 自动用 dev 默认），远端是真实的密钥。**部署脚本已通过 `--exclude '.env'` 保护远端 `.env` 永不被覆盖**。但你要在本地能解密远端导出的密文则需要把 `UPSTREAM_KEY_ENCRYPTION_KEY` 同步到本地 `.env`（这种场景只在 §5 跨机导配置时出现）。
- **数据库里的密文是绑定密钥的**：远端 `provider_keys.key_encrypted` 是用远端 `UPSTREAM_KEY_ENCRYPTION_KEY` 加密的。本机想解出来读 `provider_keys` 必须用同一把 key。普通开发用不到——你通常在 admin UI 里只看到 `key_prefix`（如 `sk-8****fb37`），看不到明文。
- **不要在本机修改 `provider_keys` / `models` / `providers` / `channel_configs` 想着推到远端**——`bin/deploy.sh` **不碰数据库**。配置同步走 §5 的独立流程。

---

## 4. 部署脚本用法

### 4.1 子命令

```bash
bin/deploy.sh                  # 全量（默认）
bin/deploy.sh --backend        # 只同步后端
bin/deploy.sh --frontend       # 只同步前端
bin/deploy.sh --skip-build     # 跳过 next build（紧急回滚代码时用）
bin/deploy.sh --no-restart     # 同步 + 安装 + 迁移 + 构建，但不重启服务
bin/deploy.sh --dry-run        # 不连远端，本地 find 模拟，展示要传哪些文件
```

### 4.2 覆盖默认值的环境变量

| 变量 | 默认 | 用途 |
|---|---|---|
| `DEPLOY_REMOTE` | `root@47.103.206.6` | ssh 目标 |
| `DEPLOY_SSH_KEY` | `~/ai/aliyun-ai01.pem` | 私钥路径 |
| `DEPLOY_REMOTE_DIR` | `/opt/cloude-gateway` | 远端安装根 |
| `DEPLOY_BACKEND_SERVICE` | `cloude-backend.service` | systemd unit |
| `DEPLOY_FRONTEND_SERVICE` | `cloude-frontend.service` | systemd unit |

### 4.3 推送前的自检清单

```bash
bin/deploy.sh --dry-run        # 看会传哪些文件，确认没误带
git status                     # 确保要推的改动都已 commit 或至少看了
git diff --stat                # 看一眼本地改了多少
```

### 4.4 推送后做什么

脚本末尾会自动做健康检查，但**看一眼**总没错：

```bash
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 \
  'curl -sS http://127.0.0.1:8082/api/health; echo'
# 期望: {"status":"ok"}
```

如果改的是数据库 schema 或加了一条新 alembic 迁移，**单独**再做一次 `pg_dump` 备份远端相关表（应急回滚用）：

```bash
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 \
  'PGPASSWORD=high_api_dev pg_dump -h 127.0.0.1 -U high_api -d high_api \
     --data-only --no-owner --inserts \
     -t providers -t provider_keys -t models -t channel_configs -t channel_keys \
     > /tmp/backup-$(date +%s).sql'
```

---

## 5. 数据库配置同步（与代码同步分开）

`bin/deploy.sh` **不同步数据库**。`models` / `providers` / `channel_configs` / `provider_keys` 这些表的增删改需要走单独的流程：

1. 在本机 admin UI（`http://localhost:3000/admin/...`）里增删改
2. 用 `pg_dump` 导出本机相关行
3. `psql` 在远端执行（事先按 `docs/deploy.md` §7 的策略备份远端数据）
4. **不要忘记给远端 `.env` 同步 `UPSTREAM_KEY_ENCRYPTION_KEY`**，否则 `provider_keys` 无法解密

具体流程可以参考之前那次推送做出来的脚本：`/tmp/cg-sync/export.py` + `sync.sql` + 远端 `psql` 执行。本机配置在另一台电脑上重做时按当时的 `/tmp/cg-sync/` 文件夹复现即可。

---

## 6. 哪些会同步 / 不会同步

| 本地 | 远端 | 说明 |
|---|---|---|
| `backend/app/`, `backend/api/`, `backend/core/`, `backend/config/`, `backend/providers/`, `backend/alembic/`, `backend/alembic.ini`, `backend/pyproject.toml`, `backend/uv.lock`, `backend/server.py`, `backend/start.sh` | ✅ | 业务代码 + 依赖锁 + 启动脚本 |
| `backend/.env` | ❌ | **永不覆盖**——保护远端真实密钥 |
| `backend/secrets/jwt_*.pem` | ❌ | **永不覆盖**——远端在首次部署时生成 |
| `backend/.venv/`, `backend/__pycache__/`, `backend/tests/` | ❌ | 远端 `uv sync` 重建 .venv；测试和缓存不需要 |
| `frontend/app/`, `frontend/components/`, `frontend/lib/`, `frontend/middleware.ts` | ✅ | 业务代码 |
| `frontend/package.json`, `frontend/package-lock.json`, `frontend/next.config.*`, `frontend/tsconfig.json`, `frontend/tailwind.config.*`, `frontend/postcss.config.*` | ✅ | 配置和锁 |
| `frontend/node_modules/`, `frontend/.next/` | ❌ | 远端 `npm ci` + `next build` 重新生成 |
| `frontend/tests/`, `frontend/.env*` | ❌ | 测试和本地环境变量 |
| `*.bak`, `*.bak-*`, `*.log`, `*.tmp`, `*.tsbuildinfo` | ❌ | 备份和缓存 |
| `.git/`, `.codegraph/`, `.understand-anything/`, `.DS_Store` | ❌ | 仓库元数据 |

---

## 7. 常见坑

1. **.env 永远在远端独享**。本地改了 `.env`（如加了新变量）**不会被推过去**。同步变量的正确做法：
   - 把变量加到 `.env.example`（这个会被推）
   - 单独在远端编辑 `/opt/cloude-gateway/backend/.env` 加这一行
   - `systemctl restart cloude-backend`

2. **新增 alembic 迁移**：本地生成 → commit → `bin/deploy.sh` 会自动同步文件 + 远端 `alembic upgrade head` 自动应用。**不要在远端手工 ALTER**（除了紧急修复）——否则下次 `alembic upgrade` 会报 schema drift。

3. **`provider_keys.key_encrypted` 永远不能跨机器搬**：密文绑定了本机（或远端）的 `UPSTREAM_KEY_ENCRYPTION_KEY`，要换机器用必须在源端解密、目标端重加密。详见 §5。

4. **首次跑脚本会在远端 `dnf install rsync`**（Alibaba Cloud Linux 3 是 RHEL 系）。Debian/Ubuntu 系统会自动改用 `apt-get`。这一步需要 root。

5. **重启会瞬断**：uvicorn `--workers 1`，重启期间 `POST /v1/messages` 大约 1-3s 返回 502。生产用可加 `--workers 2` + `systemctl reload`（reload 不在脚本里支持，自己写）。

6. **未提交的本地代码不会推**：脚本只推 working tree 的当前状态。如果 `git status` 看到一堆 untracked/modified 但还没 `git add`，**这些照样会被推**（脚本读文件系统，不读 git）。建议先 commit 再 deploy。

7. **远端 `/opt/cloude-gateway/backend/.env.bak-*` 是 sed 备份**：每次手动 `sed` 改 `.env` 都会留一份。如果堆积太多，半年清理一次即可。

8. **如果中途出错脚本没回滚**：rsync 是覆盖式同步 + `--delete`；如果同步后 `npm run build` 失败但 `rsync` 已成功，远端文件已经更新。`--no-restart` 模式不会触发服务重启但代码已下发。回滚只能靠 git 旧 commit + 重跑脚本（如果远端仓库也是 git 镜像则方便）。

---

## 8. 紧急回滚

### 8.1 代码回滚

```bash
git checkout HEAD~1 -- backend frontend
bin/deploy.sh --skip-build --no-restart    # 先同步旧代码
bin/deploy.sh                                # 跑完整流程（build + restart）
```

或者 `git revert` 一次提交再 `bin/deploy.sh`。

### 8.2 数据库回滚

`alembic downgrade -1` 退回一版：

```bash
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 \
  'cd /opt/cloude-gateway/backend && .venv/bin/python3 -m alembic downgrade -1'
```

如果是没有 alembic 迁移的纯数据变更（§5），用之前 `pg_dump` 出来的 `/tmp/backup-*.sql` 还原：

```bash
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 \
  'PGPASSWORD=high_api_dev psql -h 127.0.0.1 -U high_api -d high_api -v ON_ERROR_STOP=1 -f /tmp/backup-<timestamp>.sql'
```

### 8.3 服务起不来

```bash
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 \
  'systemctl status cloude-backend --no-pager -l; tail -50 /var/log/cloude-gateway/backend.log'
```

最常见原因：`UPSTREAM_KEY_ENCRYPTION_KEY` 缺失（`DEBUG=false` + 没设 key → `RuntimeError`）。

---

## 9. 定期清理（append-only 表 + 日志）

数据库里 `request_logs` / `usage_records` / `pending_billings` / `redemption_codes` 都是 append-only,无清理逻辑 → 不加干预的话一年下来能涨到 10GB+。日志同问题:`loguru` 配了 `rotation="50 MB"` 但默认无限期保留轮转文件。

### 9.1 清理脚本

`backend/scripts/cleanup_old_records.py` 删除过期的行,按以下默认保留期(单位:天,全部用 `CLEANUP_*_DAYS` env var 覆盖):

| 表 | 默认保留 | 备注 |
|---|---|---|
| `request_logs` | 180 | 仅删**无** `billing_record` 引用的行(无 `ON DELETE CASCADE`) |
| `usage_records` | 90 | |
| `pending_billings` (`status='dead'`) | 7 | `pending` / `settled` 永远不动 |
| `redemption_codes` (`status='issued'` 且已过期) | 7 天宽限 | `used` 留作审计,永不删 |

幂等、可重跑。`--dry-run` 只统计不删,适合先看会清多少:

```bash
# 在远端手动跑
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 \
  'cd /opt/cloude-gateway/backend && \
   .venv/bin/python -m scripts.cleanup_old_records --dry-run'

# 实际跑
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 \
  'cd /opt/cloude-gateway/backend && \
   .venv/bin/python -m scripts.cleanup_old_records'
```

输出形如:

```
request_logs: deleted 1234 rows (retention=180 days, rowcount=1234)
usage_records: 0 rows past retention; skipping
pending_billings (dead): deleted 12 rows (retention=7 days, rowcount=12)
redemption_codes (issued+expired): deleted 8 rows (retention=7 days, rowcount=8)
done. total deleted: 1254
```

### 9.2 systemd timer(自动每周)

`bin/cloude-cleanup.{service,timer}` 推到远端 `/etc/systemd/system/`,启 timer 即可每周日 03:17 自动跑:

```bash
# 一次性安装(只在远端)
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 '
  cp /opt/cloude-gateway/bin/cloude-cleanup.{service,timer} /etc/systemd/system/ &&
  systemctl daemon-reload &&
  systemctl enable --now cloude-cleanup.timer
'

# 验证 timer 已排上
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 \
  'systemctl list-timers cloude-cleanup.timer --no-pager'

# 看上次跑的结果
ssh -i ~/ai/aliyun-ai01.pem root@47.103.206.6 \
  'systemctl status cloude-cleanup.service --no-pager; \
   journalctl -u cloude-cleanup.service -n 50 --no-pager'
```

`Persistent=true` 保证错过的那周补跑一次(脚本幂等,补跑不会乱删)。

### 9.3 调保留期

在 `/opt/cloude-gateway/backend/.env` 加(然后 `systemctl restart cloude-backend` 不影响 timer,但改完想立即生效可手动跑一次脚本):

```bash
CLEANUP_REQUEST_LOG_DAYS=365
CLEANUP_USAGE_RECORD_DAYS=180
CLEANUP_PENDING_BILLING_DAYS=30
CLEANUP_REDEMPTION_GRACE_DAYS=14
```

合规要求高的场景,把保留期调大;纯 demo 可调到 7/7/3/3 加速释放。

### 9.4 日志轮转

`backend/config/logging_config.py` 已经把 `loguru` 的 `retention=10`(保留 10 份 50MB 轮转 ≈ 500MB 上限),不需额外配。`/var/log/cloude-gateway/backend.log` 是 systemd 写出去的另一份,跟 OS 默认 logrotate / journald 走;如果磁盘小,把 `/etc/systemd/journald.conf` 的 `SystemMaxUse=` 调到 500M 之类。

---

## 10. 文件清单

```
bin/deploy.sh                                    # 部署脚本
bin/cloude-cleanup.service                       # 清理 service unit(推)
bin/cloude-cleanup.timer                         # 清理 timer unit(推)
docs/deploy.md                                   # 本文档
backend/.env.example                             # 环境变量样例(推)
backend/.env                                     # 本地开发用(不推)
backend/secrets/jwt_private.pem, jwt_public.pem  # 远端生成(不推)
frontend/.env.example                            # 前端样例(推)
frontend/.env.production                         # 远端独立(不推)
```
