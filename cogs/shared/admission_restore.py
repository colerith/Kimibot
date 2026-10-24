"""Persist the admission tier across punishment and re-verification."""
import asyncio
from config import IDS
from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace


def _key(guild_id, user_id):
    return f'admission_restore:{guild_id}:{user_id}'


def remember(member):
    key = _key(member.guild.id, member.id)
    state = load_json_namespace(key, legacy_file=None, default={})
    ids = {role.id for role in member.roles}
    hatched = int(IDS['HATCHED_ROLE_ID'])
    newbie = int(IDS['VERIFICATION_ROLE_ID'])
    # A repeated penalty while already stripped must not erase the original tier.
    if hatched in ids or state.get('role_id') == hatched:
        state['role_id'] = hatched
    elif newbie in ids and not state.get('role_id'):
        state['role_id'] = newbie
    if state:
        save_json_namespace(key, state)


async def restore(member):
    key = _key(member.guild.id, member.id)
    state = await asyncio.to_thread(load_json_namespace, key, legacy_file=None, default={})
    hatched = int(IDS['HATCHED_ROLE_ID'])
    newbie = int(IDS['VERIFICATION_ROLE_ID'])
    role_id = hatched if any(r.id == hatched for r in member.roles) else state.get('role_id', newbie)
    role = member.guild.get_role(role_id)
    if role is None:
        raise ValueError('原准入身份组不存在，请联系管理员；恢复记录已保留。')
    await member.add_roles(role, reason='答题通过，恢复处罚前准入身份')
    if role_id == hatched:
        old = next((r for r in member.roles if r.id == newbie), None)
        if old:
            await member.remove_roles(old, reason='恢复破壳而出，移除低阶准入身份')
    # Consume only after Discord has accepted the role changes.
    await asyncio.to_thread(save_json_namespace, key, {})
    return role
