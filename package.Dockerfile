FROM registry.cyberspike.top:5000/huancun/pre_shovel_package

ENV DEBIAN_FRONTEND=noninteractive


RUN NTP_SERVERS="time.windows.com ntp1.aliyun.com ntp2.aliyun.com ntp3.aliyun.com ntp4.aliyun.com cn.ntp.org.cn" && \
    for server in $NTP_SERVERS; do \
        echo "尝试与NTP服务器 $server 同步时间..."; \
        if ntpdate -u "$server"; then \
            echo "时间同步成功：$server"; \
            break; \
        else \
            echo "时间同步失败：$server"; \
        fi; \
    done

WORKDIR /data
COPY . /data

# No need for pip install. Our package script would handle it anyway
