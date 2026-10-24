import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from config import IDS
from cogs.shared import admission_restore as module

class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved = {}
        self.patches = [patch.object(module, 'load_json_namespace', side_effect=lambda key, **kw: dict(self.saved.get(key, {}))),
                        patch.object(module, 'save_json_namespace', side_effect=lambda key, value: self.saved.update({key: dict(value)}))]
        for p in self.patches: p.start()
        self.new = NS(id=IDS['VERIFICATION_ROLE_ID'])
        self.old = NS(id=IDS['HATCHED_ROLE_ID'])
        self.guild = NS(id=1, get_role=lambda rid: self.old if rid == self.old.id else self.new)
        self.member = NS(id=2, guild=self.guild, roles=[], add_roles=AsyncMock(), remove_roles=AsyncMock())
    async def asyncTearDown(self):
        for p in self.patches: p.stop()
    async def test_hatched_survives_repeat_penalty(self):
        self.member.roles = [self.old, self.new]
        module.remember(self.member)
        self.member.roles = []
        module.remember(self.member)
        result = await module.restore(self.member)
        self.assertEqual(result.id, self.old.id)
        self.assertEqual(list(self.saved.values()), [{}])
    async def test_newbie_and_first_time(self):
        self.member.roles = [self.new]
        module.remember(self.member)
        self.member.roles = []
        self.assertEqual((await module.restore(self.member)).id, self.new.id)
        self.assertEqual((await module.restore(self.member)).id, self.new.id)
    async def test_failure_retains_record(self):
        self.member.roles = [self.old]
        module.remember(self.member)
        self.member.roles = []
        self.member.add_roles.side_effect = RuntimeError('network')
        with self.assertRaises(RuntimeError): await module.restore(self.member)
        self.assertEqual(next(iter(self.saved.values()))['role_id'], self.old.id)
    async def test_hatched_priority_removes_newbie(self):
        self.member.roles = [self.old, self.new]
        self.assertEqual((await module.restore(self.member)).id, self.old.id)
        self.member.remove_roles.assert_awaited_once()
