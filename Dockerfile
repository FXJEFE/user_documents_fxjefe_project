# One personal image: Python 3.11 runs the pipeline, health server, and analytics.
# Python 3.8.10 at /opt/fxjefe38 holds TensorFlow 2.10.1, Keras 2.10.0, and TA-Lib.
# The TA-Lib C library is compiled in this build and shared by both interpreters.

FROM debian:bookworm-slim AS fxjefe38

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        wget \
        libssl-dev \
        zlib1g-dev \
        libffi-dev \
        libsqlite3-dev \
        libbz2-dev \
        liblzma-dev \
        libreadline-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp
RUN wget -O ta-lib.tar.gz https://github.com/ta-lib/ta-lib/releases/download/v0.4.0/ta-lib-0.4.0-src.tar.gz \
    && tar -xzf ta-lib.tar.gz \
    && srcdir="$(find /tmp -maxdepth 1 -type d -name 'ta-lib*' | head -n 1)" \
    && cd "${srcdir}" \
    && ./configure --prefix=/usr/local \
    && make -j1 \
    && make install

RUN wget -O Python-3.8.10.tgz https://www.python.org/ftp/python/3.8.10/Python-3.8.10.tgz \
    && tar -xzf Python-3.8.10.tgz \
    && cd Python-3.8.10 \
    && ./configure --prefix=/opt/fxjefe38 --with-ensurepip=install \
    && make -j2 \
    && make install \
    && /opt/fxjefe38/bin/python3.8 -m pip install -U pip

ENV LD_LIBRARY_PATH=/usr/local/lib
COPY requirements-docker-py38.txt /tmp/requirements-docker-py38.txt
RUN /opt/fxjefe38/bin/pip install --no-cache-dir -r /tmp/requirements-docker-py38.txt \
    && /opt/fxjefe38/bin/python3.8 -c "import talib, tensorflow, keras; print(talib.__version__, tensorflow.__version__)"

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FXJEFE_FEATURE_POLICY=ACCEPT_ALL_FEATURES \
    FXJEFE_ALLOW_ALL_FEATURES=1 \
    FXJEFE_MIN_CONFIDENCE=0.77 \
    FXJEFE_HEALTH_BIND=0.0.0.0 \
    FXJEFE_PROJECT_DIR=/app \
    FXJEFE_PYTHON38=/opt/fxjefe38/bin/python3.8 \
    PYTHONPATH=/app \
    LD_LIBRARY_PATH=/usr/local/lib \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        libssl3 \
        libffi8 \
        libsqlite3-0 \
        libbz2-1.0 \
        liblzma5 \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=fxjefe38 /usr/local/lib/libta_lib.so* /usr/local/lib/
COPY --from=fxjefe38 /usr/local/include/ /usr/local/include/
COPY --from=fxjefe38 /opt/fxjefe38 /opt/fxjefe38
RUN echo /usr/local/lib > /etc/ld.so.conf.d/talib.conf && ldconfig

WORKDIR /app

COPY requirements-docker.txt /app/requirements-docker.txt
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r /app/requirements-docker.txt \
    && CFLAGS="-Wno-incompatible-pointer-types" pip install --no-cache-dir --no-build-isolation TA-Lib==0.4.28 \
    && python -c "import talib; print('talib', talib.__version__)" \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libssl3 libffi8 libsqlite3-0 libbz2-1.0 liblzma5 zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
COPY bundle/models/ /app/models/
COPY bundle/data/ /app/data/

EXPOSE 8080 8081 5555

HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD python -c "import json,urllib.request; body=json.load(urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=4)); loaded=[item for item in body.get('models') or [] if item.get('loaded')]; raise SystemExit(0 if loaded else 1)"

CMD ["python", "docker_entry.py"]
