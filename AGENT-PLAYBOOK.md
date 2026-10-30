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
- 版本镜像 tag 规则：`v1.1.0-<上游合并后的 head 短 sha>`（前缀对齐上游最新 release，2026-10-21 起为 v1.1.0，此前 2026-09-28 起为 v1.0.11；上游发新 release tag 时同步换前缀，别用自造编号。fetch 输出里出现 `[new tag] vX.Y.Z` 就是换前缀的信号）
- ⚠️ **2026-10-22 上游强制重写了 main 历史**（内容等价、SHA 全变，共同祖先退回 2025-05-08，原因未知疑似清理）。旧 fork main 与新历史分叉 3400/3300，
  GitHub Sync fork 失效、普通 merge 也不可用。当日重建：以新上游 head 为基、`git checkout main -- .` 把 fork 定制按**最终状态**搬过去（1 个提交）+ cherry-pick 当日新提交 #7300。
  **不要用逐提交 rebase**——合并期冲突解决会丢（主题定制从 tailwind.config.js 迁到 tailwind.src.css 的那次解决就丢过）。
  旧历史备份在本地分支 `main-pre-rewrite`（旧上游链 + 70 个自有提交），仅供参考不推送。此后同步恢复正常 merge 语义。

## 1. 远程仓库与网络

| remote | 地址 | 用途 |
|--------|------|------|
| `gitlab` | code.moldfun.com/ai/mcp-context-forge | **主仓库**（唯一推送目标，含全部二开） |
| `upstream` | github.com/IBM/mcp-context-forge | IBM 上游（只拉不合并不推送） |
| `origin` | github.com/649111698/mcp-context-forge | GitHub fork，**仅作异地备份**（可选推送） |

- **访问 GitHub 走本地代理**：`git -c http.proxy=http://127.0.0.1:7897 <fetch/push> ...`，失败重试 3–5 次（GFW 抖动是常态）
- **免代理备选拉上游**（代理不通时用，已验证可用）：
  `git -c http.proxy= -c https.proxy= fetch https://ghfast.top/https://github.com/IBM/mcp-context-forge.git refs/heads/main:refs/remotes/upstream/main`
- **免代理推 GitHub 备份**（2026-10-06 验证可用，fetch/push 都走 ghfast.top，不依赖 Clash）：
  `git -c http.proxy= -c https.proxy= push https://ghfast.top/https://github.com/649111698/mcp-context-forge.git main:main`
  （fork 上若有 Sync fork 空合并提交挡路，先核实 `git rev-list --no-merges main..origin/main` 为 0 再 +main:main 强推）
- 结构为 WeKnora 模式（2026-09-11 起）：单仓库 + 直接拉上游合并，**没有** GitLab 上游镜像/fork 关系（旧的 `ai/upstream/*` 已删除，不要再建）。GitLab 仓库**只保留 main 一个分支、零 tag**——上游 release tag 只留在本地作参考，永远不要 `--tags` 推到 GitLab（2026-09-11 已清理过一次 13 个上游 tag）
- GitLab 直连即可；git 凭据在 macOS 钥匙串（用户 xie）。GitLab REST API 不收密码，需要时用 OAuth 密码换 token（scope=api，2 小时过期）
- 仓库全量约 87MB（上游历史包袱：编译产物/coverage 报告/大图，我们自己的提交只占 60/3249），**属正常现象不要试图物理瘦身**——砍老历史会断掉与上游的共同祖先，merge 工作流就废了。CI/同事克隆用 `--depth 1`（仅 16MB）
- 镜像仓库：阿里云 ACR `registry.cn-shanghai.aliyuncs.com/pexetech/mcp-hub`（docker 已登录）

## 2. 本地环境

- 本地网关：`docker compose --env-file .env.aliyun.local -f docker-compose.aliyun.yml up -d`，端口 **4447**
  - 容器名 `mcp-hub-gateway`；换镜像时先 `docker rm -f mcp-hub-gateway` 再 up（compose 项目标签不一致，直接 up 会重名冲突）
- 依赖容器：Postgres `mcp-context-forge-postgres-1`（宿主 5433，库 mcp_e2e，数据卷 `mcp-context-forge_pgdata`）、Redis `mcp-hub-redis`（6380）
  - 两个容器已设 `--restart unless-stopped`（2026-09-22 起）。若发现它们 Exited，`docker start` 两个即可——网关启动会卡在 redis_isready/db_isready 探测上，症状是容器一直 starting、health 000
  - ⚠️ Postgres 是 **postgres:18**，PGDATA 布局是新式 `/var/lib/postgresql/18/docker`（卷根下有 `18/` 子目录）。若 Docker 被 prune/清空导致容器消失，用原镜像重建（卷数据不会丢）：
    `docker run -d --name mcp-context-forge-postgres-1 --restart unless-stopped -p 5433:5432 -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_DB=mcp_e2e -v mcp-context-forge_pgdata:/var/lib/postgresql postgres:18`
    （挂载点是 `/var/lib/postgresql` 不是 `.../data`；用 postgres:17 及以下会因目录非空 initdb 失败进重启循环）
  - Redis 重建：`docker run -d --name mcp-hub-redis --restart unless-stopped -p 6380:6379 redis:7`（无状态）
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
   fork 自有迁移链 `a3b5c7d9e1f2→b4c6d8e0f2a3→c5d7e9f1a3b4` 从上游 `12d4a0c7789c` 分叉；上游 v1.0.11 后的迁移链自然接在 fork head 上（当前 head 为 `d3f6a9b1c5e8`，2026-10-26 instructions 传播，链路 `c7e91a2b4d60` resource namespacing → `a4b8c1d9e2f7` → `d3f6a9b1c5e8`；c7e91a2b4d60 的直接前驱是我们 repoint 过的 `5e211ec89cad`）。
   若上游新迁移的 `down_revision` 指向 ≤`12d4a0c7789c`，会产生两个 head → 把新迁移的 `down_revision` 改指当前 fork head（参考 5e211ec89cad 文件内注释）。
3. **依赖 + 测试**（跑全集太慢，跑针对性子集 + 冒烟）：
   ```bash
   uv sync --group dev
   # 按本次改动选相关测试目录，外加 fork 自有测试：
   #   tests/unit/mcpgateway/services/test_tool_api_source_service.py
   #   tests/unit/mcpgateway/routers/ tests/unit/mcpgateway/services/ 中被改动的文件
   # ⚠️ 2026-10-10 起上游(#7180)启动即拒绝 __REPLACE_ME__ 占位符密钥，冒烟必须带真实 JWT_SECRET_KEY
   source .env.aliyun.local
   DATABASE_URL="sqlite:///./mcp.db" JWT_SECRET_KEY="$JWT_SECRET_KEY" \
     uv run python -c "import mcpgateway.main; print('IMPORT_OK')"
   ```
   已知问题（**预存在，不要修也不要慌**）：`tests/unit/mcpgateway/test_main.py` 与 `tests/e2e/test_gateway_async_lifecycle.py` 在同一批执行时后者会 3 failed（test_main 状态污染），单独跑全过。
4. **构建镜像**（完整 overlay 配方，逐坑试出来的，别改）：
   ```bash
   python3 - <<'EOF'
   from pathlib import Path
   src = Path("Containerfile").read_text()
   # 坑1: pip 引导阶段（venv + pip install uv/setuptools）走阿里云源（清华源缺 cpex-sql-sanitizer 会 404）。
   # ⚠️ 锚点用 "python3 -m venv" 续行定位：上游在 ARG 与 RUN 之间插过注释行（旧锚点 ARG+RUN 紧邻已失效），
   # 且 Step 2 的 uv 安装 RUN 同样以 use-openssl.sh 开头——那个绝不能配镜像（见坑2）。
   marker = ("RUN set -euo pipefail \\\n"
             "    && . /etc/profile.d/use-openssl.sh \\\n"
             "    && python3 -m venv /app/.venv")
   inject = ("ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/\n"
             "ENV UV_HTTP_TIMEOUT=300\n"
             "RUN set -euo pipefail \\\n"
             "    && . /etc/profile.d/use-openssl.sh \\\n"
             "    && python3 -m venv /app/.venv")
   assert src.count(marker) == 1
   src = src.replace(marker, inject)
   # 坑4: UV_HTTP_TIMEOUT=300 必须有——uv 直连 PyPI（国内慢），依赖集大改触发全量重下时
   #   默认 30s 超时会 Download timeout（2026-09-27 mcp 2.0 升级时踩过）。
   # 坑2: ⚠️ 绝对不要给 uv 配国内镜像（UV_DEFAULT_INDEX）！
   #   pyproject 有 exclude-newer="10 days"（供应链防护，只装上传超10天的包），
   #   国内镜像元数据缺 upload-time 字段 → uv 保守排除 → 依赖解析失败。
   #   uv 必须直连 PyPI。也不要设 UV_PYTHON_DOWNLOADS（只接受布尔值，设 URL 直接报错）。
   # 坑3: npm 两次 ci 前把 lockfile 重写到 npmmirror（GFW 下 registry.npmjs.org 会 EIDLETIMEOUT）
   #   ⚠️ 2026-10-21 起 #7295 把两处 npm ci 包进 if [ "$MCPGATEWAY_UI_ENABLED" = "true" ] 条件块，
   #   锚点从 "RUN npm ci" 改为 8 空格缩进的 "npm ci && \"（两处同文本，count==2 一起替换）
   npm_prefix = ("sed -i 's#https://registry.npmjs.org/#https://registry.npmmirror.com/#g' package-lock.json && "
                 "npm config set registry https://registry.npmmirror.com && ")
   m = "        npm ci && \\\n"
   assert src.count(m) == 2, f"npm ci count={src.count(m)}"
   src = src.replace(m, "        " + npm_prefix + "npm ci && \\\n")
   Path("Containerfile.mirror").write_text(src)
   print("overlay written")
   EOF
   SHA=$(git rev-parse --short HEAD)
   docker buildx build -f Containerfile.mirror --platform linux/amd64 \
     --build-arg ENABLE_RUST=false --build-arg ENABLE_RUST_MCP_RMCP=false \
     -t registry.cn-shanghai.aliyuncs.com/pexetech/mcp-hub:v1.1.0-$SHA \
     -t registry.cn-shanghai.aliyuncs.com/pexetech/mcp-hub:latest --push . \
     > /tmp/build-$SHA.log 2>&1; echo "BUILD_EXIT=$?"
   # ⚠️ 退出码要用 BUILD_EXIT 判断，不要接 | tail（管道会吞掉失败码）
   rm -f Containerfile.mirror
   ```
   **新前端（web-ui BFF+SPA）打入镜像（2026-10-30 起）**：overlay 生成脚本末尾额外追加 5 行
   （COPY webui-img/{node,app,start.sh} + ENV PATH + CMD 覆盖为 /opt/start-webui.sh——
   start.sh 在 `WEBUI_REDIS_URL` 非空时后台起 BFF（:3000，`COOKIE_SECURE/PORT/CONTEXTFORGE_URL`
   可用 `WEBUI_*` 前缀覆盖），最后 exec 原始 docker-entrypoint.sh；**WEBUI_REDIS_URL 为空 = 纯网关，
   镜像可安全原地升级**）。`webui-img/` 在宿主机 staging（gitignore 外、永不提交，同 wheelhouse-img/ 模式）：
   ```bash
   cd ../contextforge-web-ui
   npm install --no-audit --no-fund && npm run build          # SPA → server/public（内含 api:generate+typecheck）
   (cd server && npm run build && npm ci --omit=dev --no-audit --no-fund)   # BFF → server/dist + 生产依赖
   cd - && rm -rf webui-img && mkdir -p webui-img/app webui-img/node
   tar -xJf /tmp/node-22.tar.xz -C webui-img/node --strip-components=1      # npmmirror: https://cdn.npmmirror.com/binaries/node/v22.22.1/node-v22.22.1-linux-x64.tar.xz
   cp -r ../contextforge-web-ui/server/{dist,public,node_modules,package.json} webui-img/app/
   cp webui-start.sh webui-img/start.sh && chmod +x webui-img/start.sh   # 模板已进 git（仓库根 webui-start.sh）
   ```
   **刷新规则**：web-ui 仓 main 有新提交（合并上游或新功能）→ 重新 staging 再构建网关镜像；
   web-ui 没动 → webui-img/ 原样复用（node/ 208MB 可长期保留）。本地验证入口是 **4448 → 3000（新前端）**，
   4447 → 4444（网关/旧 Admin UI）不变；`WEBUI_REDIS_URL` 在 .env.aliyun.local（与网关 REDIS_URL 同实例、db 用 /1）。
   **PyPI 直连被限流/断连时的兜底（2026-10-06 实战验证）**：overlay 里在 Step 2 的 RUN 前插
   `COPY wheelhouse-img/ /tmp/wheels/`，并把该分支里 `"psycopg[c]>=3.3.3"` 改成 `"psycopg[binary]>=3.3.3"`
   （psycopg-c 无 wheel 只有 sdist），即触发上游既有的 hermetic `--no-index --find-links` 离线安装。
   wheelhouse 在宿主机备：
   ```bash
   uv export --frozen --no-hashes --no-dev --no-emit-project \
     --extra redis --extra observability --extra plugins --extra llmchat -o /tmp/wh-req.txt
   echo 'psycopg==3.3.6' >> /tmp/wh-req.txt; echo 'psycopg-binary==3.3.6' >> /tmp/wh-req.txt
   # ⚠️ --no-emit-project 必须带，否则 pip 会就地构建项目（UI 钩子）爆出几十 GB 的 zip
   # ⚠️ --platform 要列全 manylinux 系列（pip 是精确 tag 匹配不做 glibc 向下展开；
   #   cpex 系 wheel 是 manylinux_2_34，argon2-cffi-bindings 是 2_26/2_28）
   uv run --no-project python -m pip download -r /tmp/wh-req.txt -d wheelhouse-img/ \
     --index-url https://pypi.org/simple/ \
     --platform manylinux_2_34_x86_64 --platform manylinux_2_28_x86_64 --platform manylinux_2_26_x86_64 \
     --platform manylinux_2_24_x86_64 --platform manylinux_2_23_x86_64 --platform manylinux_2_22_x86_64 \
     --platform manylinux_2_21_x86_64 --platform manylinux_2_20_x86_64 --platform manylinux_2_19_x86_64 \
     --platform manylinux_2_18_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 \
     --platform manylinux2010_x86_64 --platform manylinux1_x86_64 --platform linux_x86_64 \
     --only-binary=:all: --python-version 3.12 --implementation cp
   # 另补构建后端：uv run --no-project python -m pip download 'setuptools>=78.1.1' 'wheel>=0.46.2' \
   #   -d wheelhouse-img/ --index-url https://mirrors.aliyun.com/pypi/simple/ --only-binary=:all:
   # wheelhouse-img/ 约 64MB，目录别提交（构建完可留着复用；.dockerignore 排除 wheels/ 所以必须用这个名字）
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
   #  - GET /static/css/tailwind.min.css → 200 且含 --color-indigo-600:#1677ff（fork 主题色；
   #    2026-10-20 起上游把 CSS 挪进 /static/css/ 子目录，旧路径 /static/tailwind.min.css 已 404）
   #  - DB: SELECT version_num FROM alembic_version → 应为 d3f6a9b1c5e8（2026-10-26 起 instructions 两连迁移；除非本次有新迁移）
   #  - 新前端入口: curl http://localhost:4448/healthz → 200（镜像内置 BFF；404/超时=WEBUI_REDIS_URL 未生效）
   #    浏览器开 http://localhost:4448/app/login 能登录（新前端完整链路）
   # 铸 JWT：source .env.aliyun.local 后
   #   uv run --no-project python -m mcpgateway.utils.create_jwt_token \
   #     --username admin@example.com --admin -e 30 --secret "$JWT_SECRET_KEY"
   ```
7. **提交推送（主 GitLab，备份 GitHub）**：
   ```bash
   git add docker-compose.aliyun.yml k8s/mcp-hub.yaml
   git commit -s -m "chore: bump image to v1.1.0-$SHA (sync #N)"
   git push gitlab main            # 主仓库（只推 main，不带 --tags）
   git -c http.proxy=http://127.0.0.1:7897 push origin main   # 异地备份（可选，失败重试 3-5 次）
   ```
8. **前端仓同步（2026-10-30 起与网关一起做，用户指令「前端后端都一起合并」）**：
   本地路径 `../contextforge-web-ui`，remote：`gitlab`（code.moldfun.com/ai/contextforge-web-ui，
   **唯一推送目标**）、`origin`（GitHub fork，**保持上游纯净镜像，永不推自定义提交**——用户要用它
   Sync fork 拉上游）、`upstream`（github.com/contextforge-org/contextforge-web-ui，只拉）。
   ```bash
   cd ../contextforge-web-ui
   git -c http.proxy=http://127.0.0.1:7897 fetch upstream   # 失败改 ghfast.top 备选，同 §1
   git merge upstream/main
   npm install --no-audit --no-fund                          # lockfile 变了才需要；registry 已配 npmmirror
   npm run api:generate && npm run typecheck                 # 上游刷了 openapi.json 时重生成类型
   npx vitest run                                            # 全量（~3800 用例，几分钟）
   npx eslint src server --no-error-on-unmatched-pattern || npx eslint <改动文件> --fix
   git push gitlab main                                      # 只推 gitlab！
   ```
   fork 定制文件（合并冲突高发区）：`src/App.tsx`（lazyNamed 块 + PRIVATE_ROUTE_DEFS 路由表）、
   `src/components/layout/Sidebar.tsx`（COMPONENTS_NAV_ITEMS + lucide 图标导入）、
   `src/i18n/locales/{en-US,es-ES,pt-BR}/navigation.json`（navigation.toolApis 键）、
   同目录 `index.ts`（toolApis 导入与展开）；`toolApis.json`/`tool-apis/`/`ToolApis.*` 为纯新增文件无冲突。
   ⚠️ i18n 三 locale 键必须齐平（locales.test.ts 强制），冲突解完三个文件都要看。
   MCP APIs 功能调用的网关 JSON API（/admin/tool-apis*）在网关仓，后端先同步、前端后验证。
   web-ui 暂不构建镜像（生产未部署前端；要部署时再补构建推送流程）。

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
  gateway=registry.cn-shanghai.aliyuncs.com/pexetech/mcp-hub:v1.1.0-<SHA>
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
