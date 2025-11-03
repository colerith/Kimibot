# 使用一个官方的、轻量级的Python 3.10作为基础环境
FROM python:3.10-slim

# 在集装箱里创建一个专门放我们东西的文件夹 /app
WORKDIR /app

# 先把家具清单放进去
COPY requirements.txt .

# 按照清单安装家具，并且使用国内的“加速魔法”，安装得更快更稳定！
RUN pip install -r requirements.txt --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple

# 最后，把我们所有的代码都放进去
COPY . .

# 告诉集装箱，启动的时候就念这个咒语！
CMD ["python", "main.py"]