# 一口清爽 · 饮品自动售卖机

基于 Flask、SQLite 和原生 HTML / CSS / JavaScript 的课程演示项目，支持饮品选购、模拟投币、退币、订单查询和后台管理。支付与出货均为模拟。

## 启动

需要 Python 3.9 或以上版本，在项目目录中运行。

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Windows PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

浏览器访问 [http://127.0.0.1:5000](http://127.0.0.1:5000)，按 `Ctrl+C` 停止服务。首次启动会自动创建数据库和 8 款初始饮品。

## 主要功能

- 按类别选择饮品，查看价格和库存。
- 模拟投入 1、5、10、20 元，购买后可退回剩余余额。
- 查看当前浏览器访客的最近 100 笔订单。
- 管理后台支持补货、调价、上下架和销售统计，默认密码为 `12345`。

数据保存在 `instance/` 目录，重启后保留。

## 测试

使用已安装依赖的 Python 运行：

```bash
python -m unittest discover -s tests -v
```
