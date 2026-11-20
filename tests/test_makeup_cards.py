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
        timestamp=patch.object(p,'_now_iso',side_effect=lambda: p._today()+'T12:00:00+08:00')
        timestamp.start(); self.addCleanup(timestamp.stop)
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
        for dates in [[],['2026-10-19','2026-10-20','2026-10-21','2026-10-22'],['2026-10-20']*3,['2026-10-20','2026-10-21','2026-10-27']]:
            with self.assertRaises(ValueError): makeup.use(7,9,'month',dates,'invalid')
        self.assertEqual(makeup.snapshot(7,9)['inventory']['month'],1)
        self.assertEqual(makeup.snapshot(7,9)['used'],0)

    def test_partial_card_survives_rollover_and_ledger_recovery(self):
        self.buy('previous')
        first=makeup.use(7,9,'previous',['2026-10-20','2026-10-21'],'partial')
        self.assertEqual(first['remaining'],5)
        self.assertEqual(makeup.use(7,9,'previous',['2026-10-20','2026-10-21'],'partial'),first)
        with p._points_connection() as con:
            con.execute("DELETE FROM point_sections WHERE namespace IN ('makeup_cards','makeup_receipts')")
        state=makeup.snapshot(7,9)
        self.assertEqual(state['remaining']['previous'],5)
        self.assertEqual(state['inventory']['previous'],0)
        self.assertEqual(state['used'],1)
        self.today_mock.return_value='2026-11-05'
        result=makeup.use(7,9,'previous',['2026-10-22'],'rest')
        self.assertEqual(result['remaining'],4)
        self.assertEqual(makeup.snapshot(7,9)['used'],1)

    def test_partial_capacity_and_new_card_are_separate(self):
        self.buy('month')
        makeup.use(7,9,'month',['2026-10-20'],'partial')
        self.buy('month','second')
        with self.assertRaises(ValueError):
            makeup.use(7,9,'month',['2026-10-21','2026-10-22','2026-10-23'],'too_many')
        result=makeup.use(7,9,'month',['2026-10-21','2026-10-22'],'finish')
        self.assertEqual(result['remaining'],0)
        self.assertEqual(makeup.snapshot(7,9)['inventory']['month'],1)

    def test_launch_and_rolling_window_boundaries(self):
        self.assertEqual(makeup.missing_dates(7,9,'2020-01-01')[-1],'2026-08-06')
        self.today_mock.return_value='2026-11-21'
        dates=makeup.missing_dates(7,9,'2020-01-01')
        self.assertEqual(dates[0],'2026-11-20')
        self.assertEqual(dates[-1],'2026-08-21')
        self.assertEqual(makeup.missing_dates(7,9,'2026-11-01')[-1],'2026-11-01')
        self.buy('previous')
        before=makeup.snapshot(7,9)
        with self.assertRaises(ValueError):
            makeup.use(7,9,'previous',['2026-08-20'],'expired','2020-01-01')
        self.assertEqual(makeup.snapshot(7,9),before)
        makeup.use(7,9,'previous',['2026-08-21'],'boundary','2020-01-01')
        self.today_mock.return_value='2026-08-10'
        with self.assertRaises(ValueError):
            makeup.use(7,9,'previous',['2026-08-05'],'before_launch')
        self.assertEqual(makeup.missing_dates(7,9,'2026-08-11'),[])

    def test_three_month_calendar_clamping(self):
        from datetime import date
        self.assertEqual(makeup.earliest_makeup_date('2020-01-01',date(2027,5,31)),date(2027,2,28))
        self.assertEqual(makeup.earliest_makeup_date('2020-01-01',date(2028,5,31)),date(2028,2,29))


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
        self.assertFalse(next(c for c in view.children if getattr(c,'label',None)=='确认补签并领取奖励').disabled)
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

    async def test_missing_dates_pagination_and_shop_summary(self):
        from datetime import date, timedelta
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from cogs.points.makeup_views import MissingDatesView, MakeupView
        dates=[(date(2026,10,26)-timedelta(days=i)).isoformat() for i in range(40)]
        view=MissingDatesView(7,dates)
        self.assertIn('40 天',view.embed().description)
        self.assertTrue(view.previous.disabled)
        interaction=SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
        await view.next_page.callback(interaction)
        self.assertIn(dates[25],view.embed().description)
        self.assertTrue(view.next_page.disabled)
        state={'dates':[], 'inventory':{}, 'remaining':{'previous':5}, 'balance':20,'used':1}
        with patch.object(makeup,'snapshot',return_value=state), patch.object(makeup,'missing_dates',return_value=dates):
            embed=await MakeupView(7,'2026-09-01').embed(9)
        self.assertIn('40 天',embed.description)
        self.assertIn('已开卡余量 5 天',embed.description)

    async def test_query_acknowledges_and_edits_private_response(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from cogs.points.makeup_views import show_missing_dates
        interaction=SimpleNamespace(user=SimpleNamespace(id=7,joined_at=None),guild_id=9,
            response=SimpleNamespace(defer=AsyncMock()),edit_original_response=AsyncMock())
        def missing(*args):
            interaction.response.defer.assert_awaited_once_with(ephemeral=True,invisible=False)
            return ['2026-10-20']
        with patch.object(makeup,'missing_dates',side_effect=missing):
            await show_missing_dates(interaction)
        self.assertIn('1 天',interaction.edit_original_response.call_args.kwargs['embed'].description)
        with patch.object(makeup,'missing_dates',side_effect=ValueError('无法获取入服日期')):
            await show_missing_dates(interaction)
        self.assertEqual(interaction.edit_original_response.call_args.kwargs['content'],'无法获取入服日期')
        with patch.object(makeup,'missing_dates',side_effect=RuntimeError('database failed')):
            with self.assertLogs('cogs.points.makeup_views',level='ERROR'):
                await show_missing_dates(interaction)
        self.assertIn('已记录错误',interaction.edit_original_response.call_args.kwargs['content'])
