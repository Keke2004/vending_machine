"""运行：python -m unittest discover -s tests -v。每个测试使用独立临时数据库。"""
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import create_app, get_db


class VendingMachineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {
            'TESTING': True, 'SECRET_KEY': 'test-only-key',
            'DATABASE': str(Path(self.temp.name) / 'test.sqlite3'),
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.token = self.client.get('/api/session').json['csrf_token']

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, data=None, key=None, client=None, token=None):
        return (client or self.client).post(path, json={
            **(data or {}), 'request_id': key or uuid.uuid4().hex,
        }, headers={'X-CSRF-Token': token or self.token})

    def deposit(self, amount=1000):
        return self.post('/api/deposit', {'amount_cents': amount})

    def product(self, product_id=1):
        return next(p for p in self.client.get('/api/products').json['products'] if p['id'] == product_id)

    def login(self):
        return self.post('/api/admin/login', {'password': '12345'})

    def edit(self, product_id=1, **updates):
        return self.client.patch(f'/api/admin/products/{product_id}', json={
            'stock': 12, 'price_cents': 350, 'active': 1, **updates,
        }, headers={'X-CSRF-Token': self.token})

    def test_home_and_catalog(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(len(self.client.get('/api/products').json['products']), 8)
        self.assertEqual(self.product()['price_cents'], 350)

    def test_purchase_updates_balance_stock_and_order(self):
        self.assertEqual(self.deposit().json['balance_cents'], 1000)
        response = self.post('/api/purchase', {'product_id': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['balance_cents'], 650)
        self.assertEqual(self.product()['stock'], 11)
        order = self.client.get('/api/orders').json['orders'][0]
        self.assertEqual(order['id'], response.json['order_id'])
        self.assertEqual(order['amount_cents'], 350)

    def test_insufficient_funds_changes_nothing(self):
        self.deposit(100)
        response = self.post('/api/purchase', {'product_id': 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get('/api/session').json['balance_cents'], 100)
        self.assertEqual(self.product()['stock'], 12)
        self.assertEqual(self.client.get('/api/orders').json['orders'], [])

    def test_sold_out_and_missing_product(self):
        self.deposit()
        self.assertEqual(self.post('/api/purchase', {'product_id': 8}).status_code, 409)
        self.assertEqual(self.post('/api/purchase', {'product_id': 999}).status_code, 404)
        self.assertEqual(self.client.get('/api/session').json['balance_cents'], 1000)

    def test_money_validation(self):
        for invalid in (-100, 0, 150, 100.0, True, '100', None, 1000000):
            with self.subTest(amount=invalid):
                self.assertEqual(self.post('/api/deposit', {'amount_cents': invalid}).status_code, 400)
        self.assertEqual(self.client.get('/api/session').json['balance_cents'], 0)

    def test_purchase_idempotency(self):
        self.deposit()
        key = uuid.uuid4().hex
        first = self.post('/api/purchase', {'product_id': 1}, key)
        replay = self.post('/api/purchase', {'product_id': 1}, key)
        self.assertEqual(first.json['order_id'], replay.json['order_id'])
        self.assertTrue(replay.json['replayed'])
        self.assertEqual(replay.json['balance_cents'], 650)
        self.assertEqual(self.product()['stock'], 11)
        self.assertEqual(len(self.client.get('/api/orders').json['orders']), 1)

    def test_deposit_and_refund_idempotency(self):
        key = uuid.uuid4().hex
        for _ in range(2):
            self.post('/api/deposit', {'amount_cents': 1000}, key)
        self.assertEqual(self.client.get('/api/session').json['balance_cents'], 1000)
        refund_key = uuid.uuid4().hex
        self.assertEqual(self.post('/api/refund', key=refund_key).json['refunded_cents'], 1000)
        self.deposit(500)
        result = self.post('/api/refund', key=refund_key).json
        self.assertEqual(result['refunded_cents'], 1000)
        self.assertEqual(result['balance_cents'], 500)

    def test_request_key_cannot_be_reused_for_different_operation(self):
        key = uuid.uuid4().hex
        self.post('/api/deposit', {'amount_cents': 1000}, key)
        self.assertEqual(self.post('/api/deposit', {'amount_cents': 500}, key).status_code, 409)
        self.assertEqual(self.post('/api/refund', key=key).status_code, 409)

    def test_csrf_and_json_validation(self):
        self.assertEqual(self.client.post('/api/deposit', json={'amount_cents': 100}).status_code, 403)
        self.assertEqual(self.client.post('/api/deposit', json=[], headers={'X-CSRF-Token': self.token}).status_code, 400)
        self.assertEqual(self.client.post('/api/deposit', json={'amount_cents': 100}, headers={'X-CSRF-Token': self.token}).status_code, 400)

    def test_admin_authentication_and_logout(self):
        self.assertEqual(self.client.get('/api/admin/dashboard').status_code, 401)
        self.assertEqual(self.edit().status_code, 401)
        self.assertEqual(self.post('/api/admin/login', {'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get('/api/admin/dashboard').status_code, 200)
        self.post('/api/admin/logout')
        self.assertEqual(self.edit().status_code, 401)

    def test_admin_restock_price_and_remove(self):
        self.login()
        self.assertEqual(self.edit(stock=22, price_cents=450).status_code, 200)
        self.assertEqual(self.product()['stock'], 22)
        self.assertEqual(self.product()['price_cents'], 450)
        self.edit(active=0)
        self.assertNotIn(1, [p['id'] for p in self.client.get('/api/products').json['products']])
        self.deposit()
        self.assertEqual(self.post('/api/purchase', {'product_id': 1}).status_code, 404)

    def test_admin_invalid_stock_does_not_modify(self):
        self.login()
        for invalid in (-1, 1000, 1.5, True, '12'):
            self.assertEqual(self.edit(stock=invalid).status_code, 400)
        self.assertEqual(self.product()['stock'], 12)

    def test_order_price_snapshot_survives_price_changes(self):
        self.deposit()
        self.post('/api/purchase', {'product_id': 1})
        self.login()
        self.edit(price_cents=999)
        dashboard = self.client.get('/api/admin/dashboard').json
        self.assertEqual(dashboard['stats'], {'order_count': 1, 'revenue_cents': 350})
        self.assertEqual(dashboard['orders'][0]['amount_cents'], 350)

    def test_wallets_and_orders_are_isolated(self):
        self.deposit()
        self.post('/api/purchase', {'product_id': 1})
        other = self.app.test_client()
        self.assertEqual(other.get('/api/session').json['balance_cents'], 0)
        self.assertEqual(other.get('/api/orders').json['orders'], [])

    def test_data_persists_when_app_restarts(self):
        self.login()
        self.edit(stock=42, price_cents=400)
        self.deposit()
        self.post('/api/purchase', {'product_id': 1})
        new_client = create_app(self.config).test_client()
        self.assertEqual(new_client.get('/api/products').json['products'][0]['stock'], 41)
        token = new_client.get('/api/session').json['csrf_token']
        self.post('/api/admin/login', {'password': '12345'}, client=new_client, token=token)
        self.assertEqual(new_client.get('/api/admin/dashboard').json['stats']['order_count'], 1)

    def test_concurrent_buyers_cannot_oversell_last_item(self):
        self.login()
        self.edit(stock=1)
        clients = [self.app.test_client(), self.app.test_client()]
        tokens = [client.get('/api/session').json['csrf_token'] for client in clients]
        for client, token in zip(clients, tokens):
            self.post('/api/deposit', {'amount_cents': 1000}, client=client, token=token)

        def buy(index):
            return self.post('/api/purchase', {'product_id': 1}, client=clients[index], token=tokens[index]).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(buy, [0, 1]))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(self.product()['stock'], 0)
        self.assertEqual(sorted(client.get('/api/session').json['balance_cents'] for client in clients), [650, 1000])


if __name__ == '__main__':
    unittest.main()
