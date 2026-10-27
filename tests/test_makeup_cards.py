import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from test_surprise_lottery import StorageFixture
from cogs.points import makeup, storage as p

class MakeupTests(StorageFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.clock=patch.object(p,'_today',return_value='2026-10-27')
        self.today_mock=self.clock.start(); self.addCleanup(self.clock.stop)
        p.modify_user_points(7,180,9)
    def buy(self,kind='week',i='buy'):
        return makeup.purchase(7,9,kind,i)
    def test_purchase_replay_and_streak_repair(self):
        self.buy(); self.buy()
        self.assertEqual(makeup.snapshot(7,9)['inventory']['week'],1)
        self.assertEqual(p.get_user_points(7,9),195)
        with p._points_connection() as con:
            record,key=p._db_get_user(con,7,9)
            record.update(last_sign_date='2026-10-27',streak_days=1)
            p._db_put_user(con,key,record)
            p._db_put_section(con,'daily_signins','9:2026-10-25',['7'])
        first=makeup.use(7,9,'week','2026-10-26','use','2026-01-01')
        self.assertEqual(makeup.use(7,9,'week','2026-10-26','use'),first)
        self.assertEqual(p.get_user_summary(7,9)['streak_days'],3)
        self.assertEqual(p.get_user_points(7,9),196)
        self.assertEqual(makeup.snapshot(7,9)['used'],1)
    def test_shared_monthly_cap_and_rollover(self):
        for i,kind in enumerate(['week','month','previous','month']): self.buy(kind,str(i))
        for kind,day in [('week','2026-10-26'),('month','2026-10-20'),('previous','2026-09-28')]:
            makeup.use(7,9,kind,day,day)
        with self.assertRaises(ValueError): makeup.use(7,9,'month','2026-10-19','four')
        self.assertEqual(makeup.snapshot(7,9)['inventory']['month'],1)
        self.today_mock.return_value='2026-11-05'
        self.assertEqual(makeup.snapshot(7,9)['used'],0)
        makeup.use(7,9,'month','2026-11-01','nextmonth')
    def test_invalid_dates_never_consume(self):
        self.buy('week')
        for day in ['2026-10-27','2026-10-28','invalid']:
            with self.assertRaises(ValueError): makeup.use(7,9,'week',day,day)
        with self.assertRaises(ValueError): makeup.use(7,9,'week','2026-10-25','joined','2026-10-26')
        self.assertEqual(makeup.snapshot(7,9)['inventory']['week'],1)
        self.assertEqual(makeup.snapshot(7,9)['used'],0)
    def test_seven_days_cross_month_rewards_once(self):
        self.buy('previous')
        before=p.get_user_points(7,9)
        result=makeup.use(7,9,'previous','2026-09-28','seven')
        self.assertEqual(len(result['dates']),7)
        self.assertEqual(result['dates'][-1],'2026-10-04')
        self.assertEqual(p.get_user_points(7,9),before+result['reward'])
        self.assertEqual(makeup.snapshot(7,9)['used'],1)
        self.assertEqual(makeup.use(7,9,'previous','2026-09-28','seven'),result)
        self.assertEqual(p.get_user_points(7,9),before+result['reward'])
    def test_concurrent_same_date_only_one_card(self):
        self.buy(i='a');self.buy(i='b')
        def apply(i):
            try: return makeup.use(7,9,'week','2026-10-26',str(i))
            except ValueError: return None
        with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(apply,range(4)))
        self.assertEqual(sum(bool(r) for r in results),1)
        self.assertEqual(makeup.snapshot(7,9)['inventory']['week'],1)
