# ---- 构建层：依赖装入独立 venv（利用层缓存：依赖不变时不重装） ----
FROM python:3.12-slim AS builder
# 国内 PyPI 代理加速构建（清华源）
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DEFAULT_TIMEOUT=120
WORKDIR /build
COPY pyproject.toml ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir .

# ---- 运行层：仅携带 venv 与应用代码 ----
FROM python:3.12-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["bash", "entrypoint.sh"]
