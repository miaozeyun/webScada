# ---- 构建层：Node 编译前端 ----
# 注意：本镜像的构建上下文是仓库根目录（compose 中 context: .），路径以根为准
# 基础镜像前缀：默认官方 docker.io；国内加速经 compose build-args 注入（同 server/Dockerfile）
ARG REG_PREFIX=docker.io/
FROM ${REG_PREFIX}library/node:22-alpine AS builder
# 国内 npm 镜像加速
RUN npm config set registry https://registry.npmmirror.com
WORKDIR /build
# 先装依赖（npm ci 按锁文件精确安装，构建可复现；package-lock 已入库且为 npm ci 硬依赖，故强制存在）
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# ---- 运行层：Nginx 托管静态资源并作为对外入口 ----
FROM ${REG_PREFIX}library/nginx:1.27-alpine
COPY deploy/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html
