FROM gitlab.cyberspike.top:5050/docker/python:3.12
RUN sed -i 's|http://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g; s|http://deb.debian.org/debian-security|http://mirrors.tuna.tsinghua.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources
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

# 安装 python 依赖
COPY requirements.txt /data/requirements.txt
RUN pip3 install build -i https://pypi.tuna.tsinghua.edu.cn/simple --break-system-packages
RUN python3 -m build -w
RUN pip3 install ./dist/*.whl -i https://pypi.tuna.tsinghua.edu.cn/simple --break-system-packages
