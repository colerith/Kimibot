import asyncio
import unittest
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
import discord
from cogs.welcome.data import QUIZ_QUESTIONS
from cogs.welcome.quiz_logic import draw_questions, is_correct, QUIZ_DURATION
from cogs.welcome.views import QuizQuestionView


class LogicTests(unittest.TestCase):
    def test_draw_composition(self):
        for _ in range(100):
            paper = draw_questions(QUIZ_QUESTIONS)
            self.assertEqual(len({q['id'] for q in paper}), 15)
            self.assertEqual(sum(q.get('type') == 'multiple' for q in paper), 3)

    def test_exact_set_grading(self):
        q = {'type': 'multiple', 'answers': ['A', 'C']}
        self.assertTrue(is_correct(q, ['C', 'A']))
        for value in (None, [], ['A'], ['A', 'B', 'C'], ['A', 'D'], ['A', 'A', 'C']):
            self.assertFalse(is_correct(q, value))
        self.assertTrue(is_correct({'answer': 'A'}, 'A'))
        self.assertTrue(is_correct({'answer': 'A'}, ['A']))


class InteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_staff_entry_automatically_bypasses_member_gates(self):
        from cogs.welcome.views import QuizStartView
        for owner, administrator in [(7,False),(9,True)]:
            cog = NS(sessions={}, check_cooldown=Mock(side_effect=AssertionError('no cooldown')), timer_task=AsyncMock())
            view = QuizStartView(cog)
            view._collect_risk_reasons = AsyncMock(side_effect=AssertionError('no risk gate'))
            interaction = self.interaction()
            interaction.user.guild_permissions = NS(administrator=administrator)
            interaction.guild = NS(owner_id=owner)
            interaction.channel_id = 1
            with patch('cogs.welcome.views.has_verification_role', return_value=True):
                await view.start_quiz.callback(interaction)
            self.assertTrue(cog.sessions[7]['test_mode'])
            self.assertIn('测试模式', interaction.followup.send.call_args.kwargs['embed'].description)
            await asyncio.sleep(0)

    async def test_test_settlement_has_no_membership_or_public_side_effects(self):
        from cogs.welcome.cog import WelcomeCog
        cog = WelcomeCog.__new__(WelcomeCog)
        cog.sessions = {7:dict(test_mode=True, questions=[{'answer':'A'}]*10, answers={i:['A'] for i in range(10)})}
        cog.history = {}
        cog._send_public_log = Mock()
        interaction = self.interaction()
        interaction.response.is_done = Mock(return_value=True)
        with patch('cogs.shared.admission_restore.restore', new_callable=AsyncMock) as restore:
            await cog.finalize_quiz(interaction,7)
            restore.assert_not_awaited()
        self.assertEqual(cog.history,{})
        cog._send_public_log.assert_not_called()
        self.assertIn('100.0/100',interaction.edit_original_response.call_args.kwargs['embed'].description)
        self.assertIn('测试模式',interaction.edit_original_response.call_args.kwargs['embed'].title)

    async def asyncSetUp(self):
        quota = patch("cogs.welcome.attempts.quota_text", return_value="今日剩余 2/3，测试不占次数")
        quota.start()
        self.addCleanup(quota.stop)
        self.question = dict(type='multiple', question='测试', options=dict(A='甲', B='乙', C='丙', D='丁'), answers=['A','C'])
        self.session = dict(questions=[self.question, {'question':'单选','options':dict(A='甲',B='乙'),'answer':'A'}],
            answers={}, drafts={}, lock=asyncio.Lock(), start_time=discord.utils.utcnow())
        self.cog = NS(sessions={7:self.session}, finalize_quiz=AsyncMock())
        self.view = QuizQuestionView(self.cog, 7, 0)

    def interaction(self, values=None):
        return NS(guild_id=9, guild=NS(id=9), user=NS(id=7), data={'values': values or []}, response=NS(defer=AsyncMock(),send_message=AsyncMock()),
                  followup=NS(send=AsyncMock()),edit_original_response=AsyncMock())

    async def test_draft_restore_confirm_and_repeat(self):
        await self.view.select_callback(self.interaction(['C','A']))
        self.assertEqual(self.session['answers'], {})
        restored = QuizQuestionView(self.cog, 7, 0)
        self.assertEqual({o.value for o in restored.children[0].options if o.default}, {'A','C'})
        self.assertEqual(restored.children[0].max_values, 4)
        self.assertFalse(restored.children[1].disabled)
        await asyncio.gather(restored.confirm_callback(self.interaction()), restored.confirm_callback(self.interaction()))
        self.assertEqual(self.session['answers'], {0:['C','A']})
        self.cog.finalize_quiz.assert_not_awaited()
        await self.view.select_callback(self.interaction(['B']))
        self.assertEqual(self.session['answers'][0], ['C','A'])

    async def test_empty_invalid_and_expired(self):
        await self.view.confirm_callback(self.interaction())
        await self.view.select_callback(self.interaction(['Z']))
        self.assertEqual(self.session['answers'], {})
        self.session['start_time'] -= timedelta(seconds=QUIZ_DURATION+1)
        await self.view.select_callback(self.interaction(['A','C']))
        self.assertEqual(self.session['answers'], {})
        self.cog.finalize_quiz.assert_awaited_once()
        self.assertTrue(self.cog.finalize_quiz.call_args.kwargs['is_timeout'])

    async def test_old_session_cannot_change_new_paper(self):
        self.cog.sessions[7] = dict(self.session)
        await self.view.select_callback(self.interaction(['A','C']))
        self.assertEqual(self.session['drafts'], {})

    async def test_last_question_finalizes_once(self):
        self.session['answers'][0] = ['A','C']
        view = QuizQuestionView(self.cog, 7, 1)
        await asyncio.gather(view.select_callback(self.interaction(['A'])), view.select_callback(self.interaction(['B'])))
        self.cog.finalize_quiz.assert_awaited_once()
        self.assertEqual(self.session['answers'][1], ['A'])

    async def test_real_settlement_grades_lists_and_restores_once(self):
        from cogs.welcome.cog import WelcomeCog
        from config import IDS
        cog = WelcomeCog.__new__(WelcomeCog)
        paper = [dict(question='单选', options={'A':'甲','B':'乙'}, answer='A') for _ in range(8)] + [self.question]*2
        session = dict(questions=paper, answers={0:['A'],1:['A'],2:['A'],3:['A'],8:['C','A'],9:['A','C']})
        cog.sessions = {7:session}
        cog.history = {}
        cog._send_public_log = Mock()
        member = NS(send=AsyncMock(), display_name="测试成员", display_avatar=NS(url="https://example.com/avatar.png"))
        interaction = self.interaction()
        interaction.guild = NS(id=9, name="测试社区", fetch_member=AsyncMock(return_value=member))
        interaction.response.is_done = Mock(return_value=True)
        with patch('cogs.shared.admission_restore.restore', new_callable=AsyncMock,
                   return_value=NS(id=IDS['HATCHED_ROLE_ID'], name='破壳而出')) as restore:
            await asyncio.gather(cog.finalize_quiz(interaction,7), cog.finalize_quiz(interaction,7))
            restore.assert_awaited_once()
        self.assertEqual(cog._send_public_log.call_args.args[2:4], (60, True))
        self.assertNotIn(7, cog.sessions)
        member.send.assert_awaited_once()
