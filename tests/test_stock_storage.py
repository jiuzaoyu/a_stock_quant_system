import pytest

from src.collector.stock import StockStorage


@pytest.fixture
def storage():
    return StockStorage()


@pytest.fixture
def conn(storage):
    c = storage.connect()
    storage.init_schema(c)
    yield c
    c.rollback()
    storage.return_conn(c)


class TestSyncStockList:
    def test_insert_new_stocks_with_active_false(self, storage, conn):
        records = [
            {"code": "999999", "name": "测试股A", "market": "sh"},
            {"code": "888888", "name": "测试股B", "market": "sz"},
        ]
        storage.sync_stock_list(conn, records)

        cur = conn.cursor()
        cur.execute("SELECT code, name, market, active FROM stock_info WHERE code IN ('999999','888888') ORDER BY code")
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0] == ("888888", "测试股B", "sz", False)
        assert rows[1] == ("999999", "测试股A", "sh", False)

    def test_update_existing_does_not_change_active(self, storage, conn):
        cur = conn.cursor()
        cur.execute("INSERT INTO stock_info (code, name, market, active) VALUES ('777777','旧名称','sh',TRUE) "
                    "ON CONFLICT(code) DO UPDATE SET active=TRUE")

        records = [{"code": "777777", "name": "新名称", "market": "sh"}]
        storage.sync_stock_list(conn, records)

        cur.execute("SELECT code, name, market, active FROM stock_info WHERE code='777777'")
        row = cur.fetchone()
        assert row == ("777777", "新名称", "sh", True)


class TestGetActiveCodes:
    def test_returns_only_active_codes(self, storage, conn):
        cur = conn.cursor()
        cur.execute("INSERT INTO stock_info (code, name, market, active) VALUES ('666666','活跃股','sh',TRUE)")
        cur.execute("INSERT INTO stock_info (code, name, market, active) VALUES ('555555','非活跃股','sz',FALSE)")

        codes = storage.get_active_codes(conn)
        assert codes == ["666666"]

    def test_returns_empty_when_no_active(self, storage, conn):
        cur = conn.cursor()
        cur.execute("INSERT INTO stock_info (code, name, market, active) VALUES ('444444','全非活跃','sh',FALSE)")

        codes = storage.get_active_codes(conn)
        assert codes == []
