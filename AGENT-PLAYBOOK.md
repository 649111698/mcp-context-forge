# AGENT-PLAYBOOK — Pexetech/mcp-hub 二开运维手册（给 AI 智能体看的操作规程）

> 本文件是 fork 定制部分的唯一权威操作手册。上游仓库的通用规范见 `AGENTS.md`（不要修改上游内容）。
> 任何智能体接手本仓库的同步/构建/部署工作，**先完整读完本文件再动手**。

## 0. 全景：这个 fork 是什么

- 上游：IBM 开源的 MCP 网关（ContextForge），公司用于金蝶云星空 REST API 联邦（pexetech/mcp-hub）
- fork 定制内容：
  - `tool_apis` 二开功能（MCP API 定义保存 + 一键同步到工具目录）：`mcpgateway/admin.py`（/admin/tool-apis 路由）、`mcpgateway/templates/tool_apis_partial.html`、`mcpgateway/services/tool_api_source_service.py`、`mcpgateway/db.py` + `mcpgateway/schemas.py` 对应模型
  - 上述页面/服务的**中文化**（只汉化 fork 自有文案，上游文案不动，避免同步冲突）
  - 3 个自定义 alembic 迁移（tool_api_sources 表，链路见 §3）
  - 部署文件：`docker-compose.aliyun.yml`、`k8s/mcp-hub.yaml`、`.env.aliyun.local`（gitignored）
- 版本镜像 tag 规则：`v1.0.10-<上游合并后的 head 短 sha>`（v1.0.10 对齐上游 release，别用自造的 v1.0.14/16/20 旧编号）

## 1. 远程仓库与网络

| remote | 地址 | 用途 |
|--------|------|------|
| `gitlab` | code.moldfun.com/ai/mcp-context-forge | **主仓库**（唯一推送目标，含全部二开） |
| `upstream` | github.com/IBM/mcp-context-forge | IBM 上游（只拉不合并不推送） |
| `origin` | github.com/649111698/mcp-context-forge | GitHub fork，**仅作异地备份**（可选推送） |

- **访问 GitHub 走本地代理**：`git -c http.proxy=http://127.0.0.1:7897 <fetch/push> ...`，失败重试 3–5 次（GFW 抖动是常态）
- **免代理备选拉上游**（代理不通时用，已验证可用）：
  `git -c http.proxy= -c https.proxy= fetch https://ghfast.top/https://github.com/IBM/mcp-context-forge.git refs/heads/main:refs/remotes/upstream/main`
- 结构为 WeKnora 模式（2026-09-11 起）：单仓库 + 直接拉上游合并，**没有** GitLab 上游镜像/fork 关系（旧的 `ai/upstream/*` 已删除，不要再建）。GitLab 仓库**只保留 main 一个分支、零 tag**——上游 release tag 只留在本地作参考，永远不要 `--tags` 推到 GitLab（2026-09-11 已清理过一次 13 个上游 tag）
- GitLab 直连即可；git 凭据在 macOS 钥匙串（用户 xie）。GitLab REST API 不收密码，需要时用 OAuth 密码换 token（scope=api，2 小时过期）
- 仓库全量约 87MB（上游历史包袱：编译产物/coverage 报告/大图，我们自己的提交只占 60/3249），**属正常现象不要试图物理瘦身**——砍老历史会断掉与上游的共同祖先，merge 工作流就废了。CI/同事克隆用 `--depth 1`（仅 16MB）
- 镜像仓库：阿里云 ACR `registry.cn-shanghai.aliyuncs.com/pexetech/mcp-hub`（docker 已登录）

## 2. 本地环境

- 本地网关：`docker compose --env-file .env.aliyun.local -f docker-compose.aliyun.yml up -d`，端口 **4447**
  - 容器名 `mcp-hub-gateway`；换镜像时先 `docker rm -f mcp-hub-gateway` 再 up（compose 项目标签不一致，直接 up 会重名冲突）
- 依赖容器：Postgres `mcp-context-forge-postgres-1`（宿主 5433，库 mcp_e2e）、Redis `mcp-hub-redis`（6380）
  - 两个容器已设 `--restart unless-stopped`（2026-09-22 起）。若发现它们 Exited，`docker start` 两个即可——网关启动会卡在 redis_isready/db_isready 探测上，症状是容器一直 starting、health 000
- 敏感文件（**永不提交**）：`.env.aliyun.local`（DATABASE_URL/JWT_SECRET_KEY/IMAGE_TAG/DEFAULT_USER_PASSWORD 等）、`.deploy-credentials.txt`
- macOS 本机 venv 装不了 psycopg-c（无 libpq），**导入冒烟必须覆盖** `DATABASE_URL="sqlite:///./mcp.db"`

## 3. 同步流程（用户说「同步」/「fork了」时执行）

1. **拉上游合并**（不依赖 GitHub fork，用户无需任何操作）：
   ```bash
   git -c http.proxy=http://127.0.0.1:7897 fetch upstream \
     || git -c http.proxy= -c https.proxy= fetch \
          https://ghfast.top/https://github.com/IBM/mcp-context-forge.git \
          refs/heads/main:refs/remotes/upstream/main   # 免代理备选
   git merge upstream/main
   ```
2. **⚠️ alembic 多头检查（每次必做，漏了会启动崩溃循环）**：
   ```bash
   git diff main..origin/main --stat -- mcpgateway/alembic/   # 有输出才需要处理
   cd mcpgateway && alembic heads    # 必须只有一个 head
   ```
   fork 自有迁移链 `a3b5c7d9e1f2→b4c6d8e0f2a3→c5d7e9f1a3b4` 从上游 `12d4a0c7789c` 分叉，当前 fork head 为 `5e211ec89cad`。
   若上游新迁移的 `down_revision` 指向 ≤`12d4a0c7789c`，会产生两个 head → 把新迁移的 `down_revision` 改指当前 fork head（参考 5e211ec89cad 文件内注释）。
3. **依赖 + 测试**（跑全集太慢，跑针对性子集 + 冒烟）：
   ```bash
   uv sync --group dev
   # 按本次改动选相关测试目录，外加 fork 自有测试：
   #   tests/unit/mcpgateway/services/test_tool_api_source_service.py
   #   tests/unit/mcpgateway/routers/ tests/unit/mcpgateway/services/ 中被改动的文件
   DATABASE_URL="sqlite:///./mcp.db" uv run python -c "import mcpgateway.main; print('IMPORT_OK')"
   ```
   已知问题（**预存在，不要修也不要慌**）：`tests/unit/mcpgateway/test_main.py` 与 `tests/e2e/test_gateway_async_lifecycle.py` 在同一批执行时后者会 3 failed（test_main 状态污染），单独跑全过。
4. **构建镜像**（完整 overlay 配方，逐坑试出来的，别改）：
   ```bash
   python3 - <<'EOF'
   from pathlib import Path
   src = Path("Containerfile").read_text()
   # 坑1: pip 引导阶段走阿里云源（清华源缺 cpex-sql-sanitizer 会 404）
   marker = "ARG ENABLE_PROFILING=false\nRUN set -euo pipefail \\\n    && . /etc/profile.d/use-openssl.sh"
   inject = ("ARG ENABLE_PROFILING=false\n"
             "ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/\n"
             "RUN set -euo pipefail \\\n    && . /etc/profile.d/use-openssl.sh")
   assert src.count(marker) == 1
   src = src.replace(marker, inject)
   # 坑2: ⚠️ 绝对不要给 uv 配国内镜像（UV_DEFAULT_INDEX）！
   #   pyproject 有 exclude-newer="10 days"（供应链防护，只装上传超10天的包），
   #   国内镜像元数据缺 upload-time 字段 → uv 保守排除 → 依赖解析失败。
   #   uv 必须直连 PyPI。也不要设 UV_PYTHON_DOWNLOADS（只接受布尔值，设 URL 直接报错）。
   # 坑3: npm 两次 ci 前把 lockfile 重写到 npmmirror（GFW 下 registry.npmjs.org 会 EIDLETIMEOUT）
   npm_prefix = ("sed -i 's#https://registry.npmjs.org/#https://registry.npmmirror.com/#g' package-lock.json && "
                 "npm config set registry https://registry.npmmirror.com && ")
   m1 = "RUN npm ci && \\\n"
   assert src.count(m1) == 1
   src = src.replace(m1, "RUN " + npm_prefix + "npm ci && \\\n")
   m2 = "RUN npm ci\n"
   assert src.count(m2) == 1
   src = src.replace(m2, "RUN " + npm_prefix + "npm ci\n")
   Path("Containerfile.mirror").write_text(src)
   print("overlay written")
   EOF
   SHA=$(git rev-parse --short HEAD)
   docker buildx build -f Containerfile.mirror --platform linux/amd64 \
     --build-arg ENABLE_RUST=false --build-arg ENABLE_RUST_MCP_RMCP=false \
     -t registry.cn-shanghai.aliyuncs.com/pexetech/mcp-hub:v1.0.10-$SHA \
     -t registry.cn-shanghai.aliyuncs.com/pexetech/mcp-hub:latest --push . \
     > /tmp/build-$SHA.log 2>&1; echo "BUILD_EXIT=$?"
   # ⚠️ 退出码要用 BUILD_EXIT 判断，不要接 | tail（管道会吞掉失败码）
   rm -f Containerfile.mirror
   ```
5. **bump 三处 tag**（sed 全局替换旧 tag → 新 tag）：
   - `docker-compose.aliyun.yml:11`（IMAGE_TAG 默认值）
   - `k8s/mcp-hub.yaml:76`（生产镜像）
   - `.env.aliyun.local:23`（IMAGE_TAG）
6. **重建本地 4447 并验证**：
   ```bash
   docker rm -f mcp-hub-gateway
   docker compose --env-file .env.aliyun.local -f docker-compose.aliyun.yml up -d
   # 验证清单（全部通过才算完成）：
   #  - curl http://localhost:4447/health → 200，容器 RestartCount=0，日志无 alembic MultipleHeads
   #  - 铸 JWT 后 GET /tools → 12 个（数量变了要查明原因）
   #  - POST /api/logs/search → total > 0（结构化日志链路）
   #  - GET /admin/tool-apis/partial → 200 且含「已保存」（中文页）
   #  - DB: SELECT version_num FROM alembic_version → 应为 5e211ec89cad（除非本次有新迁移）
   # 铸 JWT：source .env.aliyun.local 后
   #   uv run --no-project python -m mcpgateway.utils.create_jwt_token \
   #     --username admin@example.com --admin -e 30 --secret "$JWT_SECRET_KEY"
   ```
7. **提交推送（主 GitLab，备份 GitHub）**：
   ```bash
   git add docker-compose.aliyun.yml k8s/mcp-hub.yaml
   git commit -s -m "chore: bump image to v1.0.10-$SHA (sync #N)"
   git push gitlab main            # 主仓库（只推 main，不带 --tags）
   git -c http.proxy=http://127.0.0.1:7897 push origin main   # 异地备份（可选，失败重试 3-5 次）
   ```

## 4. 生产环境（K8s）升级 runbook

生产：`http://218.4.196.186:30085`，命名空间 `mcp-hub`，Deployment `mcp-hub-gateway`。

```bash
# 1. 密码（#6570 要求 ≥12 位，短了会启动崩溃循环）
kubectl -n mcp-hub patch secret mcp-hub-secrets \
  -p '{"stringData":{"DEFAULT_USER_PASSWORD":"至少12位的新密码"}}'
# 2. 日志落库变量（System Logs 功能需要，ERROR 级别会滤掉全部常规事件）
kubectl -n mcp-hub set env deploy/mcp-hub-gateway \
  STRUCTURED_LOGGING_DATABASE_ENABLED=true LOG_LEVEL=INFO
# 3. 滚动升级镜像
kubectl -n mcp-hub set image deploy/mcp-hub-gateway \
  gateway=registry.cn-shanghai.aliyuncs.com/pexetech/mcp-hub:v1.0.10-<SHA>
kubectl -n mcp-hub rollout status deploy/mcp-hub-gateway
```

- ⚠️ 仓库里 `k8s/mcp-hub.yaml` 的 Secret 是 CHANGE_ME 占位符，**绝对不能直接 apply 到生产**（会抹掉真实 DATABASE_URL/JWT_SECRET_KEY），只能用 patch 按键合并
- 崩溃循环日志特征：`default_user_password: too short (8 chars, minimum 12)` → 回到第 1 步

## 5. 红线（做错会出事故）

1. 永不提交 `.env.aliyun.local`、`.deploy-credentials.txt`、任何真实密钥/签名
2. 永不 `kubectl apply` 仓库版 Secret 到生产
3. 推送目标只有两个：`gitlab`（主）和 `origin`（备份）。上游只在 GitHub，**拉过来合并即可，永远不要往任何远端再单独维护上游镜像**
4. 汉化只碰 fork 自有文案；上游模板文案动了会给用户的 GitHub Sync fork 制造冲突
5. 上游文件若确需小改（如 5e211ec89cad 的 down_revision repoint），必须带注释说明是 fork 定制，方便未来合并时识别
6. 没有用户指令（「fork了」等）不要主动构建/部署/推送
