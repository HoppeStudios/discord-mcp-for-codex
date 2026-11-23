import asyncio
from contextlib import asynccontextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('adapter', Path(__file__).resolve().parents[1]/'browser_adapter.py')
adapter=importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
URL='https://discord.com/channels/@me/111111111111111111'


class Sender:
    STATE='STATE'
    def __init__(self):
        self.username='fixture_user'
        self.url=URL
        self.draft=''
        self.submits=0
        self.switch_before_enter=False
        self.pending=False
        self.after_reload=False
        self.received=None
        self.loading_once=False
        self.history_rows=[{'id':'fixture-message-id','author_name':'Fixture','author_id':None,'failed':False}]
    def validate_url(self,url):
        if url!=URL: raise ValueError('Use one exact Discord conversation URL.')
    def split_text(self,text):
        if not text.strip():raise ValueError('Empty message')
        return [text]
    def empty(self,text):return not text.strip()
    async def call(self,session,name,args):
        if name=='new_page':self.url=args['url']
        if name=='press_key' and args['key']=='Enter':self.submits+=1
        return ''
    async def evaluate(self,session,function):
        if function==adapter.IDENTITY:
            if self.loading_once:
                self.loading_once=False
                return {'url':self.url,'login':False,'accounts':[{}]}
            return {'url':self.url,'login':False,'accounts':[{'username':self.username,'display_name':'Fixture'}]}
        if function==self.STATE:return {'url':self.url,'editors':[{'label':'Message @Fixture','text':self.draft}]}
        if 'author_id:avatar.match' in function:return self.history_rows
        return [{'url':URL,'name':'Fixture','label':'Fixture (direct message)'}]
    async def ready(self,*args):
        if args[2]!='Message @Fixture':raise ValueError('Wrong recipient')
    def save_receipt(self,path,receipt):path.write_text(json.dumps(receipt),'utf-8')
    async def send(self,session,url,label,content,request_id,root,prepare=False):
        self.received=content
        path=Path(root)/(hashlib.sha256(request_id.encode()).hexdigest()+'.json')
        if self.pending:raise RuntimeError('delivery_unknown')
        if self.draft:raise RuntimeError('draft_present')
        await self.ready(session,url,label)
        if path.exists():return {'status':'already_verified','submitted_now':0}
        if prepare:return {'status':'draft_ready','prepared_part':1}
        if self.switch_before_enter:self.username='other_user'
        await self.call(session,'press_key',{'key':'Enter'})
        self.after_reload=True
        path.write_text(json.dumps({'parts':[{'message_id':'fixture-message-id','status':'persisted_after_reload'}]}),'utf-8')
        print('fixture progress must not become MCP stdout')
        return {'status':'persisted_after_reload','submitted_now':1}


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.sender=Sender()
        self.backend=adapter.BrowserAdapter(self.sender,self.temp.name)
        @asynccontextmanager
        async def session():yield object()
        self.backend.session=session
    def tearDown(self):self.temp.cleanup()
    def send(self,**kw):
        params=dict(channel_url=URL,composer_label='Message @Fixture',expected_sender='fixture_user',content='Exact text\nŽluťoučký 🧭',request_id='stable-operation')
        return self.backend.deliver(**(params|kw))
    async def test_sender_mismatch_stops_before_helper(self):
        with self.assertRaisesRegex(RuntimeError,'sender_mismatch'):await self.send(expected_sender='other_user')
        self.assertIsNone(self.sender.received)
        self.assertEqual(self.sender.submits,0)
    async def test_waits_for_populated_visible_account(self):
        self.sender.loading_once=True
        self.assertEqual((await self.backend.personal_identity())['sender']['username'],'fixture_user')
    async def test_account_switch_before_enter_cannot_submit(self):
        self.sender.switch_before_enter=True
        with self.assertRaisesRegex(RuntimeError,'sender_mismatch'):await self.send()
        self.assertEqual(self.sender.submits,0)
    async def test_exact_text_success_and_same_receipt_retry(self):
        result=await self.send()
        self.assertEqual(result['status'],'persisted_after_reload')
        self.assertEqual(result['message_ids'],['fixture-message-id'])
        self.assertEqual(self.sender.received,'Exact text\nŽluťoučký 🧭')
        self.assertTrue(self.sender.after_reload)
        self.assertEqual((await self.send())['status'],'already_verified')
        self.assertEqual(self.sender.submits,1)
    async def test_pending_delivery_does_not_submit(self):
        self.sender.pending=True
        with self.assertRaisesRegex(RuntimeError,'delivery_unknown'):await self.send()
        self.assertEqual(self.sender.submits,0)
    async def test_draft_and_wrong_recipient_are_preserved(self):
        self.sender.draft='Existing draft'
        with self.assertRaisesRegex(RuntimeError,'draft_present'):await self.send()
        self.assertEqual(self.sender.draft,'Existing draft')
        self.sender.draft=''
        with self.assertRaisesRegex(ValueError,'Wrong recipient'):await self.send(composer_label='Message @SomeoneElse')
        self.assertEqual(self.sender.submits,0)
    async def test_prepare_never_submits(self):
        self.assertEqual((await self.send(prepare=True))['status'],'draft_ready')
        self.assertEqual(self.sender.submits,0)
    async def test_existing_legacy_receipt_is_not_evaded(self):
        key=hashlib.sha256(b'stable-operation').hexdigest()
        (Path(self.temp.name)/(key+'.json')).write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'legacy_receipt'):await self.send()
        self.assertEqual(self.sender.submits,0)
    async def test_receipt_cannot_switch_sender(self):
        await self.send(prepare=True)
        self.sender.username='other_user'
        with self.assertRaisesRegex(RuntimeError,'different sender'):await self.send(expected_sender='other_user')
        self.assertEqual(self.sender.submits,0)
    async def test_inspection_reports_draft_without_changing_it(self):
        self.sender.draft='Preserve me'
        result=await self.backend.inspect_conversation(URL,'fixture_user')
        self.assertTrue(result['draft_present'])
        self.assertEqual(self.sender.draft,'Preserve me')
        self.assertEqual(self.sender.submits,0)
    async def test_invalid_route_and_request_stop_before_session(self):
        with self.assertRaises(ValueError):await self.send(channel_url='https://discord.com/api/v10/users/@me')
        with self.assertRaises(ValueError):await self.send(request_id='../escape')
        self.assertIsNone(self.sender.received)
    async def pending_receipt(self,status='submission_pending'):
        await self.send(prepare=True)
        key=hashlib.sha256(b'stable-operation').hexdigest()
        path=Path(self.temp.name)/(key+'.json')
        digest=hashlib.sha256((URL+'\0'+'Exact text\nŽluťoučký 🧭').encode()).hexdigest()
        path.write_text(json.dumps({'content_sha256':digest,'parts':[{'status':status,'prior_message_ids':[]}]}),'utf-8')
        return path
    def verify(self):
        return self.backend.verify_delivery(URL,'Message @Fixture','fixture_user','Exact text\nŽluťoučký 🧭','stable-operation')
    async def test_pending_receipt_verified_without_resubmission(self):
        path=await self.pending_receipt()
        result=await self.verify()
        self.assertEqual(result['message_ids'],['fixture-message-id'])
        self.assertEqual(result['submitted_now'],0)
        self.assertEqual(self.sender.submits,0)
        self.assertEqual(json.loads(path.read_text())['parts'][0]['status'],'persisted_after_reload')
    async def test_ambiguous_history_cannot_resolve_receipt(self):
        path=await self.pending_receipt()
        self.sender.history_rows*=2
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):await self.verify()
        self.assertEqual(json.loads(path.read_text())['parts'][0]['status'],'submission_pending')
        self.assertEqual(self.sender.submits,0)
    async def test_wrong_history_author_cannot_resolve_receipt(self):
        await self.pending_receipt()
        self.sender.history_rows[0]['author_name']='Other'
        with self.assertRaisesRegex(RuntimeError,'author'):await self.verify()
        self.assertEqual(self.sender.submits,0)
    async def test_unsubmitted_part_cannot_be_marked_delivered(self):
        await self.pending_receipt('not_submitted')
        with self.assertRaisesRegex(RuntimeError,'unsubmitted'):await self.verify()
    def test_changed_helper_hash_refuses_import(self):
        path=Path(self.temp.name)/'helper.py'
        path.write_text("raise RuntimeError('must not import')")
        with patch.dict(os.environ,{'DISCORD_BROWSER_HELPER':str(path),'DISCORD_BROWSER_HELPER_SHA256':'0'*64}):
            with self.assertRaisesRegex(RuntimeError,'helper changed'):adapter.load_sender()


if __name__=='__main__':unittest.main()
