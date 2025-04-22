# 使用 Python 官方镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 复制项目文件到容器
COPY . /app

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 设置默认启动命令
CMD ["python", "main.py"]
