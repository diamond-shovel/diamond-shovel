FROM gitlab.cyberspike.top:5050/docker/python:3.13.3
RUN sed -i 's|http://deb.debian.org/debian|http://mirrors.huaweicloud.com/debian|g; s|http://deb.debian.org/debian-security|http://mirrors.huaweicloud.com/debian-security|g' /etc/apt/sources.list.d/debian.sources
RUN apt update && apt install -y \
    curl \
    nmap \
    netcat-openbsd \
    git \
    chromium \
    libnss3 \
    libatk1.0-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxrandr2 \
    libgtk-3-0 \
    libxdamage1 \
    libxfixes3 \
    libgbm1

RUN apt update && \
    apt install -y libasound2 || \
    (apt install -y libasound2t64 || apt install -y liboss4-salsa-asound2)

RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
RUN echo "Asia/Shanghai" > /etc/timezone

# 设置工作目录
WORKDIR /data
COPY . /data

RUN pip config set global.index-url https://mirrors.huaweicloud.com/repository/pypi/simple && \
    pip3 install build setuptools setuptools-scm --break-system-packages && \
    python3 -m build -wn && \
    pip3 install ./dist/*.whl --break-system-packages

RUN diamond-shovel -I

EXPOSE 8848
ENTRYPOINT ["diamond-shovel", "-D", "-U", "http://0.0.0.0:8848/"]
