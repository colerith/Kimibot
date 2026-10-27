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

    def test_compatibility_snapshot_preserves_cards_and_receipts(self):
        self.buy()
        snapshot=p.load_points_data()
        p.save_points_data(snapshot)
        self.assertEqual(makeup.snapshot(7,9)['inventory']['week'],1)
        self.buy()  # Receipt must also survive.
        self.assertEqual(p.get_user_points(7,9),195)
        makeup.use(7,9,'week',['2026-10-26'],'use')
        p.save_points_data(p.load_points_data())
        self.assertEqual(makeup.snapshot(7,9)['dates'],['2026-10-26'])
        self.assertEqual(makeup.snapshot(7,9)['used'],1)

    def test_recover_erased_inventory_from_ledger_without_extra_charge(self):
        self.buy('week','one'); self.buy('month','three')
        makeup.use(7,9,'week',['2026-10-26'],'used')
        balance=p.get_user_points(7,9)
        with p._points_connection() as con:
            con.execute("DELETE FROM point_sections WHERE namespace IN ('makeup_cards','makeup_receipts')")
        state=makeup.snapshot(7,9)
        self.assertEqual(state['inventory'],{'week':0,'month':1})
        self.assertEqual(state['used'],1)
        self.assertEqual(state['dates'],['2026-10-26'])
        self.buy('month','three')
        makeup.use(7,9,'week',['2026-10-26'],'used')
        self.assertEqual(p.get_user_points(7,9),balance)

    def test_nonconsecutive_dates_and_missing_list(self):
        self.buy('month')
        targets=['2026-09-30','2026-10-12','2026-10-26']
        result=makeup.use(7,9,'month',targets,'multi','2026-09-29')
        self.assertEqual(result['dates'],targets)
        missing=makeup.missing_dates(7,9,'2026-09-29')
        self.assertNotIn('2026-10-27',missing)
        self.assertNotIn('2026-09-28',missing)
        self.assertTrue(set(targets).isdisjoint(missing))
        self.assertIn('2026-10-25',missing)
        self.assertEqual(missing,sorted(missing,reverse=True))

    def test_invalid_multi_selection_no_consumption(self):
        self.buy('month')
        for dates in [['2026-10-20'],['2026-10-20']*3,['2026-10-20','2026-10-21','2026-10-27']]:
            with self.assertRaises(ValueError): makeup.use(7,9,'month',dates,'invalid')
        self.assertEqual(makeup.snapshot(7,9)['inventory']['month'],1)
        self.assertEqual(makeup.snapshot(7,9)['used'],0)


class MakeupPickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_page_selection_preserved_and_completion_disables(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from datetime import date, timedelta
        from cogs.points.makeup_views import MakeupDatesView
        dates=[(date(2026,10,26)-timedelta(days=i)).isoformat() for i in range(40)]
        panel=SimpleNamespace(owner=7,interaction_check=AsyncMock(return_value=True),embed=AsyncMock(return_value=None))
        parent=SimpleNamespace(edit=AsyncMock())
        view=MakeupDatesView(panel,'month',dates,'2026-01-01',parent)
        interaction=SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock(),send_message=AsyncMock(),defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()),edit_original_response=AsyncMock(),guild_id=9,id=123,data={})
        selector=view.children[0]
        selector._interaction=interaction
        selector._selected_values=dates[:2]
        await selector.callback(interaction)
        self.assertEqual(view.selected,set(dates[:2]))
        await next(c for c in view.children if getattr(c,'label',None)=='下一页').callback(interaction)
        selector=view.children[0]
        selector._interaction=interaction
        selector._selected_values=[dates[25]]
        await selector.callback(interaction)
        self.assertEqual(view.selected,set(dates[:2]+[dates[25]]))
        await next(c for c in view.children if getattr(c,'label',None)=='上一页').callback(interaction)
        self.assertTrue(all(o.default for o in view.children[0].options[:2]))
        with patch.object(makeup,'use',return_value={'message':'ok'}) as use:
            await view.confirm(interaction)
            await view.confirm(interaction)
            self.assertEqual(use.call_count,1)
            self.assertEqual(use.call_args.args[3],sorted(dates[:2]+[dates[25]]))
        self.assertIsNone(interaction.edit_original_response.call_args.kwargs['view'])
        parent.edit.assert_awaited_once()
