"""饮品自动售卖机：Flask + SQLite，金额统一使用整数「分」。"""
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException


SEED_PRODUCTS = [
    (1, '经典可乐', 'COLA · 330 mL', '气泡饮料', 350, 12, '#a63629', 'COLA', 'can'),
    (2, '青柠气泡水', 'LIME SODA · 330 mL', '气泡饮料', 450, 8, '#65884b', 'LIME', 'can'),
    (3, '茉莉绿茶', 'JASMINE TEA · 500 mL', '茶与咖啡', 400, 15, '#c6a866', '茉莉', 'bottle'),
    (4, '鲜橙果汁', 'ORANGE · 300 mL', '果汁', 600, 6, '#df8938', 'ORANGE', 'bottle'),
    (5, '矿泉水', 'MINERAL WATER · 550 mL', '饮用水', 200, 20, '#90b6bd', 'WATER', 'bottle'),
    (6, '醇香拿铁', 'LATTE · 250 mL', '茶与咖啡', 800, 5, '#a48169', 'LATTE', 'can'),
    (7, '白桃乌龙', 'PEACH OOLONG · 500 mL', '茶与咖啡', 500, 3, '#c28c8c', '白桃', 'bottle'),
    (8, '葡萄果汁', 'GRAPE · 300 mL', '果汁', 650, 0, '#897591', 'GRAPE', 'bottle'),
]


class APIError(Exception):
    """携带中文提示与 HTTP 状态码，由统一处理器转换为 JSON。"""

    def __init__(self, message, status=400):
        self.message = message
        self.status = status


def get_db():
    """在当前请求中复用连接，请求结束时由 close_db 释放。"""
    if 'db' not in g:
        from flask import current_app
        g.db = sqlite3.connect(current_app.config['DATABASE'], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def integer(value, name, minimum, maximum):
    """校验整数及取值范围；布尔值不能作为金额或库存提交。"""
    if type(value) is not int or not minimum <= value <= maximum:
        raise APIError(f'{name}必须为 {minimum}–{maximum} 之间的整数。')
    return value


def body():
    """只接受 JSON 对象，避免后续接口读取无效的数据结构。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise APIError('请提交 JSON 对象。')
    return data


def admin_required(function):
    """为管理接口统一检查登录状态。"""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not session.get('is_admin'):
            raise APIError('请先登录管理员。', 401)
        return function(*args, **kwargs)
    return wrapped


def balance(db):
    """读取当前浏览器会话对应的钱包余额，单位为分。"""
    row = db.execute(
        'SELECT balance_cents FROM wallets WHERE id = ?',
        (session['wallet_id'],),
    ).fetchone()
    return row['balance_cents']


def wallet_operation(kind, data, action):
    """串行事务 + 幂等键，避免重复点击或并发请求重复扣款。"""
    request_id = data.get('request_id')
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
        raise APIError('缺少有效的请求编号。')
    payload = json.dumps(
        {k: v for k, v in data.items() if k != 'request_id'},
        sort_keys=True,
    )
    db = get_db()
    with db:
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute(
            'SELECT * FROM operations WHERE wallet_id = ? AND request_id = ?',
            (session['wallet_id'], request_id),
        ).fetchone()
        if previous:
            if previous['kind'] != kind or previous['payload'] != payload:
                raise APIError('请求编号已用于其他操作，请重新操作。', 409)
            result = json.loads(previous['response'])
            result['balance_cents'] = balance(db)
            result['replayed'] = True
            return jsonify(result)
        result = action(db)
        result['balance_cents'] = balance(db)
        db.execute('INSERT INTO operations VALUES (?, ?, ?, ?, ?)',
                   (session['wallet_id'], request_id, kind, payload, json.dumps(result)))
    return jsonify(result)


def create_app(test_config=None):
    """创建应用并初始化数据库，测试时可传入独立配置。"""
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=str(Path(app.instance_path) / 'vending.sqlite3'),
        ADMIN_PASSWORD='12345',
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(exist_ok=True)
    if not app.config.get('SECRET_KEY'):
        key_path = Path(app.instance_path) / 'secret.key'
        # 独占创建，多个进程首次启动时也不会覆盖彼此的密钥。
        try:
            with key_path.open('x') as key_file:
                key_file.write(secrets.token_hex(32))
            key_path.chmod(0o600)
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or key_path.read_text().strip()

    @app.teardown_appcontext
    def close_db(exception=None):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    with app.app_context():
        db = get_db()
        db.executescript((Path(app.root_path) / 'schema.sql').read_text())
        with db:
            db.executemany('''INSERT OR IGNORE INTO products
                (id, name, subtitle, category, price_cents, stock, color, label, shape)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', SEED_PRODUCTS)

    @app.before_request
    def prepare_session():
        """为 API 请求准备钱包，并校验修改数据时的 CSRF 令牌。"""
        if not request.path.startswith('/api/'):
            return
        if request.method in ('POST', 'PATCH', 'DELETE'):
            token = session.get('csrf_token')
            if not token or not hmac.compare_digest(token.encode(), request.headers.get('X-CSRF-Token', '').encode()):
                raise APIError('会话校验失败，请刷新页面后重试。', 403)
        if 'wallet_id' not in session:
            session['wallet_id'] = uuid.uuid4().hex
            session['csrf_token'] = secrets.token_hex(24)
        db = get_db()
        with db:
            db.execute('INSERT OR IGNORE INTO wallets (id) VALUES (?)', (session['wallet_id'],))

    @app.after_request
    def headers(response):
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(APIError)
    def api_error(error):
        return jsonify(error=error.message), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith('/api/'):
            return jsonify(error=error.description), error.code
        return error

    @app.errorhandler(sqlite3.OperationalError)
    def database_error(error):
        app.logger.error('Database error: %s', error)
        return jsonify(error='数据库暂时不可用，请稍后重试。'), 503

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/session')
    def session_info():
        return jsonify(
            balance_cents=balance(get_db()),
            csrf_token=session['csrf_token'],
            is_admin=bool(session.get('is_admin')),
        )

    @app.get('/api/products')
    def products():
        rows = get_db().execute(
            'SELECT * FROM products WHERE active = 1 ORDER BY id',
        )
        return jsonify(products=[dict(row) for row in rows])

    @app.post('/api/deposit')
    def deposit():
        data = body()
        amount = integer(data.get('amount_cents'), '投币金额', 100, 2000)
        if amount not in (100, 500, 1000, 2000):
            raise APIError('仅支持 1、5、10、20 元模拟投币。')

        def action(db):
            if balance(db) + amount > 100000:
                raise APIError('余额上限为 1000 元，请先购买或退币。')
            db.execute('UPDATE wallets SET balance_cents = balance_cents + ? WHERE id = ?',
                       (amount, session['wallet_id']))
            return {'message': '投币成功', 'deposited_cents': amount}
        return wallet_operation('deposit', data, action)

    @app.post('/api/purchase')
    def purchase():
        data = body()
        product_id = integer(data.get('product_id'), '商品编号', 1, 2147483647)

        def action(db):
            product = db.execute('SELECT * FROM products WHERE id = ? AND active = 1',
                                 (product_id,)).fetchone()
            if not product:
                raise APIError('饮品不存在或已下架。', 404)
            if product['stock'] <= 0:
                raise APIError('这款饮品已售罄，请选择其他饮品。', 409)
            if balance(db) < product['price_cents']:
                raise APIError('余额不足，请先投币。', 409)
            order_id = 'VM' + uuid.uuid4().hex[:16].upper()
            db.execute('UPDATE wallets SET balance_cents = balance_cents - ? WHERE id = ?',
                       (product['price_cents'], session['wallet_id']))
            db.execute('UPDATE products SET stock = stock - 1 WHERE id = ?', (product_id,))
            db.execute('''INSERT INTO orders (id, wallet_id, product_id, product_name, amount_cents)
                          VALUES (?, ?, ?, ?, ?)''',
                       (order_id, session['wallet_id'], product_id, product['name'], product['price_cents']))
            return {'message': '购买成功，请取走饮品', 'order_id': order_id,
                    'product_name': product['name'], 'amount_cents': product['price_cents']}
        return wallet_operation('purchase', data, action)

    @app.post('/api/refund')
    def refund():
        def action(db):
            refunded = balance(db)
            db.execute('UPDATE wallets SET balance_cents = 0 WHERE id = ?', (session['wallet_id'],))
            return {'message': '退币成功', 'refunded_cents': refunded}
        return wallet_operation('refund', body(), action)

    @app.get('/api/orders')
    def orders():
        """只返回当前访客的订单，同一秒内的订单按插入顺序倒序。"""
        rows = get_db().execute(
            '''SELECT id, product_name, amount_cents, created_at
               FROM orders
               WHERE wallet_id = ?
               ORDER BY created_at DESC, rowid DESC
               LIMIT 100''',
            (session['wallet_id'],),
        )
        return jsonify(orders=[dict(row) for row in rows])

    @app.post('/api/admin/login')
    def login():
        password = body().get('password')
        if not isinstance(password, str) or not hmac.compare_digest(
                password.encode(), app.config['ADMIN_PASSWORD'].encode()):
            raise APIError('管理员密码不正确。', 401)
        session['is_admin'] = True
        return jsonify(message='登录成功')

    @app.post('/api/admin/logout')
    def logout():
        session.pop('is_admin', None)
        return jsonify(message='已退出管理员')

    @app.get('/api/admin/dashboard')
    @admin_required
    def dashboard():
        db = get_db()
        stats = dict(db.execute(
            '''SELECT COUNT(*) AS order_count,
                      COALESCE(SUM(amount_cents), 0) AS revenue_cents
               FROM orders''',
        ).fetchone())
        rows = db.execute(
            '''SELECT id, product_name, amount_cents, created_at
               FROM orders
               ORDER BY created_at DESC, rowid DESC
               LIMIT 100''',
        )
        product_rows = db.execute('SELECT * FROM products ORDER BY id')
        return jsonify(
            stats=stats,
            products=[dict(row) for row in product_rows],
            orders=[dict(row) for row in rows],
        )

    @app.patch('/api/admin/products/<int:product_id>')
    @admin_required
    def update_product(product_id):
        """在同一事务中保存库存、价格和上架状态。"""
        data = body()
        stock = integer(data.get('stock'), '库存', 0, 999)
        price = integer(data.get('price_cents'), '价格（分）', 100, 99900)
        active = integer(data.get('active'), '上架状态', 0, 1)
        db = get_db()
        with db:
            result = db.execute(
                '''UPDATE products
                   SET stock = ?, price_cents = ?, active = ?
                   WHERE id = ?''',
                (stock, price, active, product_id),
            )
            if result.rowcount == 0:
                raise APIError('饮品不存在。', 404)
        return jsonify(message='饮品信息已保存')

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', '5000')), debug=False)
