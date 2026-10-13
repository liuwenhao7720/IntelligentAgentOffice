# V-FLO 智能办公系统单机部署说明（无 K8s）
# 目标机：公司服务器 192.168.2.22（金品 JP KU2250-G2 · 海光 32C/64T · 256GB · NVMe×2）

## 0. 硬件准备
1. 系统盘 2×960GB NVMe → RAID1（LSI 9460-16I）
2. **尽快加装数据盘**（剩余盘位）→ RAID5/10 → 挂载 `/data`
3. 目录：
   ```bash
   mkdir -p /opt/vflo-smart-office /data/{pg,backups,logs,uploads,certs}
   ```

## 1. 系统与 Docker
```bash
# 以 Rocky/openEuler/Ubuntu 为例
yum install -y docker docker-compose-plugin   # 或 apt install docker.io docker-compose-plugin
systemctl enable --now docker
docker compose version
```
离线环境：提前下载 docker-ce 与镜像包 `postgres:16-alpine nginx:alpine redis:7-alpine python:3.11-slim` 导入 `docker load`。

## 2. 部署应用
```bash
cd /opt/vflo-smart-office
# 上传工程代码（含 docker-compose.yml / Dockerfile / app / web / deploy）
cp .env.example .env
vim .env    # 填写 SECRET_KEY、模型 Key、简道云 Key（勿提交 Git）
docker compose build
docker compose up -d
curl -s http://127.0.0.1:8000/api/health
```

## 3. Nginx / HTTPS
- 默认 `deploy/nginx.conf` 将 `/` 静态文件与 `/api` 反代到 app:8000
- 生产放入证书到 `deploy/certs/`，并强制 HTTPS

## 4. 备份
- `backup` 服务每日 `pg_dump` 到 `/data/backups`，默认保留 30 天
- 每周将备份目录拷贝至移动硬盘或异机
- **每月恢复演练**：`gunzip -c vflo_xxx.sql.gz | psql ...`

## 5. 常用命令
```bash
docker compose ps
docker compose logs -f app
docker compose restart app
docker compose down   # 不删数据卷
```

## 6. 资源建议（256GB 内存机器）
| 服务 | CPU | 内存 |
|------|-----|------|
| PostgreSQL | 4–6 | 32–48GB |
| app (4 workers) | 8–12 | 16–24GB |
| nginx | 1–2 | 2–4GB |
| backup/预留 | 2+ | 8GB+ |

## 7. 安全清单
- [ ] 修改服务器默认口令，限制 SSH 来源
- [ ] `.env` 权限 `chmod 600`
- [ ] 数据库仅监听 127.0.0.1
- [ ] 关闭不必要的系统服务
- [ ] 日志轮转与磁盘告警（>80%）

## 7.1 角色权限与企业微信扫码登录上线 checklist
- [ ] 角色体系：staff 员工 / manager 部门经理 / compliance 合规官 / admin 管理员。
      首个 admin 由 `DEV_ADMIN_USERS` 白名单产生，之后一律在「管理看板 → 用户管理」分配角色，
      不再改环境变量；系统内置防误锁（不能改自己角色/停用自己）
- [ ] 企微管理后台：将 `WECOM_REDIRECT_URI` 的域名/IP:端口 登记为自建应用的
      「可信域名 / 授权回调域」，值需与 `.env` 完全一致（内网入口示例
      `http://192.168.2.22:8008/api/v1/auth/wecom/callback`）
- [ ] 服务器需能出网访问 `qyapi.weixin.qq.com`（扫码换号）；不可达时系统自动 503 降级，
      用户可临时用开发登录（若 ENABLE_DEV_LOGIN=1）
- [ ] 生产务必 `ENABLE_DEV_LOGIN=0`：登录页只剩扫码入口，dev 账号停止新增
- [ ] 历史 dev 账号（dev_* 前缀）与企微账号是独立身份；全员切换扫码后，
      在用户管理中停用不再使用的 dev 账号
- [ ] 验证：`curl http://127.0.0.1:8000/api/v1/auth/wecom/config` 返回 `wecom_enabled:true`，
      登录页出现「企业微信扫码登录」按钮，扫码后回落首页自动进入

## 8. 故障恢复（单机 RTO≤4h）
1. 重装 OS + Docker
2. 拉起 compose
3. 恢复最近备份
4. 配置 `.env` 与证书
5. 验证 `/api/health` 与登录


## 9. 内网离线安装（首次装 Docker）

`ash
# 联网机打包
bash deploy/offline-install.sh prepare
# 内网服务器
bash deploy/offline-install.sh install
bash deploy/offline-install.sh verify
`

详见《离线安装包准备清单.md》。compose 资源配额（上限）：
| 服务 | CPU | 内存 |
|------|-----|------|
| db | 6 | 40g |
| app | 12 | 20g |
| nginx | 2 | 3g |
| redis | 2 | 6g |
| backup | 2 | 4g |
| **合计** | **24** | **~73g**（预留约 8C/180GB） |
