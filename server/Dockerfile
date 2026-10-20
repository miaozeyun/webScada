# ---- 构建层：依赖装入独立 venv（利用层缓存：依赖不变时不重装） ----
FROM python:3.12-slim AS builder
# 默认国内清华源加速；网络受限时可 --build-arg PIP_INDEX_URL=... 覆盖（如官方源 + HTTP(S)_PROXY）
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120
WORKDIR /build
COPY pyproject.toml ./
# 只装第三方依赖（运行层直接 COPY 源码，无需把项目本身打成包；
# 此前 `pip install .` 在仅含 pyproject 的目录里打 wheel 依赖源码，靠旧缓存层掩盖）
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir \
      $(python -c "import tomllib; print(' '.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))")

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
