from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock
from usr.plugins.minecraft_control.helpers import runtime

class RuntimeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patches = [patch.object(runtime, 'STATE', {'busy':True,'output':'new run'}),
            patch.object(runtime, 'ACTIVE', 'context'), patch.object(runtime, 'RUN', 'new'),
            patch.object(runtime.launcher, 'snapshot', return_value={'online':True}),
            patch.object(runtime.launcher, 'TOOLS', [{'name':'get_status'}])]
        for p in self.patches:p.start()
        self.context=SimpleNamespace(id='context',get_data=lambda key:True)
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
    async def test_old_completion_cannot_overwrite_new_request(self):
        async def result():return 'old result'
        with patch.object(runtime.launcher,'stop_game',new_callable=AsyncMock) as stop:
            await runtime.finish(SimpleNamespace(result=result),'context','old')
            stop.assert_not_awaited()
        self.assertEqual(runtime.STATE['output'],'new run')
    async def test_unknown_tool_never_crosses_launcher(self):
        with patch.object(runtime.launcher,'game_operation',new_callable=AsyncMock) as call:
            with self.assertRaises(ValueError):await runtime.call_tool(self.context,'run_shell',{})
            call.assert_not_awaited()
    async def test_tool_request_uses_current_task(self):
        with patch.object(runtime.launcher,'game_operation',new_callable=AsyncMock,return_value={'ok':True}) as call:
            self.assertEqual(await runtime.call_tool(self.context,'get_status',{}),{'ok':True})
            call.assert_awaited_once_with({'action':'tool','run':'new','tool':'get_status','params':{}})
    async def test_stop_revokes_task_before_remote_stop(self):
        async def stopped(run):
            self.assertIsNone(runtime.RUN)
            self.assertEqual(run,'new')
        with patch.object(runtime.AgentContext,'get',return_value=None), patch.object(runtime.launcher,'stop_game',side_effect=stopped):
            await runtime.submit('stop','','')
        with self.assertRaises(ValueError):await runtime.call_tool(self.context,'get_status',{})

    async def test_chat_is_bound_once_and_old_connections_are_ignored(self):
        connection={'context_id':'parent'};state={'chat_epoch':'epoch','requests':[{'id':1,'text':'check status'}]}
        with patch.object(runtime.launcher,'ACTIVE',connection),patch.object(runtime.launcher,'chat_enabled',return_value=True),patch.object(runtime,'submit',new_callable=AsyncMock) as submit:
            await runtime.receive_chat(connection,state);await runtime.receive_chat(connection,state)
            submit.assert_awaited_once_with('build','check status','parent',chat_reply=True)
            await runtime.receive_chat({'context_id':'other'},state);self.assertEqual(submit.await_count,1)

    async def test_disabled_and_busy_chat_are_not_replayed(self):
        connection={'context_id':'parent'};state={'chat_epoch':'epoch','requests':[{'id':1,'text':'check'}]}
        with patch.object(runtime.launcher,'ACTIVE',connection),patch.object(runtime.launcher,'chat_enabled',return_value=False),patch.object(runtime,'submit',new_callable=AsyncMock) as submit:
            await runtime.receive_chat(connection,state);submit.assert_not_awaited()
        state['requests']=[{'id':2,'text':'another request'}]
        with patch.object(runtime.launcher,'ACTIVE',connection),patch.object(runtime.launcher,'chat_enabled',return_value=True),patch.object(runtime,'submit',new_callable=AsyncMock,side_effect=ValueError('Busy')) as submit,patch.object(runtime,'notice',new_callable=AsyncMock) as notice:
            await runtime.receive_chat(connection,state);await runtime.receive_chat(connection,state)
            self.assertEqual(submit.await_count,1);notice.assert_awaited_once_with('Busy')

if __name__=='__main__':unittest.main()
