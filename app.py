#!/usr/bin/env python3
"""智服 AI - local-first MVP. Python 3.9+, zero third-party dependencies.

This is a LOCAL demo, not a production ITSM service. No authentication.
Knowledge records are fictional samples. Optional Dify Chatbot/Chatflow connection
is configured server-side via environment variables.
"""
import json
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime
from uuid import UUID
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('ZHIFU_DB_PATH', str(ROOT / 'zhifu_demo.sqlite3')))
PORT = int(os.environ.get('ZHIFU_PORT', '8765'))
DIFY_API_KEY = os.environ.get('DIFY_API_KEY', '').strip()
DIFY_API_BASE = os.environ.get('DIFY_API_BASE', 'https://api.dify.ai/v1').strip().rstrip('/')
DIFY_USER = 'zhifu_employee_demo'
DIFY_KB_API_KEY = os.environ.get('DIFY_KB_API_KEY', '').strip()
DIFY_DATASET_ID = os.environ.get('DIFY_DATASET_ID', '').strip()

MAX_BODY = 50_000
WRITE_LOCK = threading.Lock()

SEED_KB = [
    ('办公网络', '如何连接公司 Wi-Fi', '演示企业的办公 Wi-Fi 名称为 ZHIFU-Office（仅为虚构示例）。\n1. 在电脑系统设置中打开 Wi-Fi，选择 ZHIFU-Office。\n2. 使用公司统一身份账号和密码进行认证。\n3. 若提示认证失败，请先确认账号未过期，再关闭并重新开启 Wi-Fi。\n4. 仍无法连接时，记录错误提示及设备型号，并提交 IT 工单。', 'WiFi 无线网 网络 上网 连接'),
    ('办公网络', 'VPN 无法登录的排查方法', '1. 检查当前网络能否正常访问外部网站。\n2. 确认 VPN 客户端已升级至企业要求的版本。\n3. 重新输入统一身份认证账号并检查二次验证。\n4. 如出现错误码，请记录错误码，提交 IT 工单给网络支持人员。\n注意：请勿将密码或动态验证码填写在工单里。', 'VPN 远程办公 登录'),
    ('账号权限', '忘记办公账号密码怎么办', '1. 打开演示企业的统一身份认证门户。\n2. 选择“忘记密码”，通过预留手机或企业邮箱验证身份。\n3. 设置新密码后等待数分钟，再重新登录。\n4. 若无法完成身份验证，请创建“账号权限”工单，人工核验后处理。\n不要在聊天中发送密码。', '密码 账号 重置 登录 认证'),
    ('办公设备', '打印机脱机或无法打印', '1. 确保打印机电源和网络连接正常。\n2. 检查电脑是否选择了正确的打印机。\n3. 查看打印队列，取消卡住的任务后重试。\n4. 如果仍显示脱机，请提供打印机位置、型号及错误提示并提交 IT 工单。', '打印机 纸张 脱机 打印'),
    ('软件应用', '办公软件安装与授权', '1. 在公司软件中心查找已批准的应用。\n2. 按提示下载和安装。\n3. 如果提示没有授权，请提供软件名称、业务用途和部门，创建“软件应用”工单。\n4. 不要自行安装来历不明的软件包。', 'Office Excel 软件 安装 授权'),
    ('账号权限', '新员工开通企业系统权限', '1. 先由直属主管确认所需权限和业务目的。\n2. 提交“账号权限”工单并选择所需系统。\n3. IT 管理员核对审批结果后开通。\n4. 权限开通完成后由申请人验证。\n演示流程不代表真实企业的审批规则。', '权限 新员工 系统 开通 申请'),
    ('办公设备', '电脑运行缓慢的基础排查', '1. 先保存工作并重启电脑。\n2. 检查磁盘剩余空间是否充足。\n3. 关闭不必要的后台应用。\n4. 若持续缓慢，记录异常时间、设备型号和截图并创建 IT 工单。', '电脑 卡顿 慢 性能 系统'),
    ('安全规范', '遇到可疑邮件如何处理', '1. 不点击可疑链接，也不下载未知附件。\n2. 不向对方提供账号密码及验证码。\n3. 保存邮件主题、发件人信息并上报 IT 安全人员。\n4. 如已误点链接，请立即报备并按 IT 指引修改密码。', '钓鱼 邮件 安全 验证码 可疑'),
]


def connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
            title TEXT NOT NULL, content TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS knowledge_sync (
            knowledge_id INTEGER PRIMARY KEY,
            document_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '未同步',
            error TEXT NOT NULL DEFAULT '',
            submitted_at TEXT NOT NULL DEFAULT ''
          );
          CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            description TEXT NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL,
            status TEXT NOT NULL, requester TEXT NOT NULL, assignee TEXT NOT NULL DEFAULT '待分配',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
          );
        ''')
        if db.execute('SELECT COUNT(*) FROM knowledge').fetchone()[0] == 0:
            now = datetime.now().strftime('%Y-%m-%d %H:%M')
            db.executemany('INSERT INTO knowledge (category,title,content,keywords,created_at) VALUES (?,?,?,?,?)',
                           [(*row, now) for row in SEED_KB])
        db.commit()


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def response_body(handler, status, value):
    data = json.dumps(value, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(data)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.end_headers()
    handler.wfile.write(data)


def clean_text(text, limit=2000):
    if not isinstance(text, str):
        return ''
    return text.strip()[:limit]


def categorize(text):
    t = text.lower()
    rules = [
      ('账号权限', ['密码', '账号', '权限', '登录', '认证', '账户']),
      ('办公网络', ['wifi','wi-fi','无线','网络','vpn','上网','断网','连接']),
      ('办公设备', ['电脑','打印','设备','鼠标','键盘','卡顿']),
      ('软件应用', ['软件','office','excel','安装','应用','授权']),
      ('安全规范', ['邮件','钓鱼','病毒','安全','诈骗']),
    ]
    return next((cat for cat, triggers in rules if any(x in t for x in triggers)), '其他问题')


def bigrams(s):
    s = s.lower()
    for filler in ('怎么办', '怎么样', '怎么', '如何', '请问', '公司', '我想', '这个', '那个', '什么'): s = s.replace(filler, '')
    s = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]+', '', s)
    return set(s[i:i+2] for i in range(len(s)-1))


def retrieve(query, docs, limit=3):
    qt = bigrams(query)
    qlow = query.lower()
    scores = []
    for doc in docs:
        title = doc['title'].lower()
        keywords = doc['keywords'].lower()
        content = doc['content'].lower()
        ts = bigrams(title + ' ' + keywords)
        cs = bigrams(content)
        overlap_title = len(qt & ts) / max(1, len(qt))
        overlap_body = len(qt & cs) / max(1, len(qt))
        exact = sum(0.2 for kw in re.split(r'\s+', keywords) if len(kw) >= 2 and kw in qlow)
        score = overlap_title * 0.7 + overlap_body * 0.15 + min(exact, .5)
        if score >= 0.08:
            scores.append((score, dict(doc)))
    scores.sort(key=lambda x: x[0], reverse=True)
    return [dict(d, score=round(score, 3)) for score, d in scores[:limit]]


def local_answer(query):
    with connect() as db:
        docs = [dict(row) for row in db.execute('SELECT * FROM knowledge').fetchall()]
    matches = retrieve(query, docs)
    if not matches:
        return {
          'answer': '本地知识库没有找到足够相关的操作指南。建议点击“转人工工单”，由 IT 支持人员跟进。\n\n（当前为本地检索模式，尚未接入大语言模型。）',
          'matched': [], 'resolved': False, 'source': 'local'
        }
    best = matches[0]
    return {
      'answer': '根据演示知识库，找到相关指南：\n\n【' + best['title'] + '】\n' + best['content'] +
                '\n\n以上为模拟企业知识，仅供项目演示。若仍未解决，可转人工工单。\n（当前为本地检索模式，非大模型生成。）',
      'matched': [{'id':x['id'], 'title':x['title'], 'category':x['category']} for x in matches],
      'resolved': True, 'source': 'local'
    }


# Dify Chatflow 回复末尾的机器可读分类标记（仅用于演示版）。
# 保证不会把分类元数据泄漏到面向员工的聊天气泡中。
VALID_AI_CATEGORIES = ('办公网络', '账号权限', '办公软件', '办公设备', '其他问题')
AI_CATEGORY_SUFFIX = re.compile(r'\s*\[\[ZHIFU_CATEGORY:\s*([^\]\r\n]{1,40}?)\s*\]\]\s*$', re.I)


# 部分推理模型会把 <think> 内容写入 answer；仅允许正式回答进入员工界面。
# 支持多段、大小写变体和未闭合标签（未闭合部分直接丢弃，避免泄漏）。
THINK_BLOCK = re.compile(r'<\s*think(?:\s+[^>]*)?\s*>.*?<\s*/\s*think\s*>', re.I | re.S)
THINK_OPEN = re.compile(r'<\s*think(?:\s+[^>]*)?\s*>', re.I)
THINK_CLOSE = re.compile(r'<\s*/\s*think\s*>', re.I)
THINK_PARTIAL_OPEN = re.compile(r'<\s*thi(?:n(?:k)?)?(?:\s+[^>]*)?$', re.I)


def remove_model_thinking(text):
    """Only remove model reasoning, never expose unfinished <think> content."""
    if not isinstance(text, str):
        return ''
    result = THINK_BLOCK.sub('', text)
    # 可能出现模型输出长度截断，留下 <think> 但没有 </think>。
    unmatched = THINK_OPEN.search(result)
    if unmatched:
        result = result[:unmatched.start()]
    result = THINK_CLOSE.sub('', result)
    result = THINK_PARTIAL_OPEN.sub('', result)
    return result.strip()


def split_ai_answer(raw_answer):
    """Return (clean_answer, category_or_none), never trust an unknown class."""
    if not isinstance(raw_answer, str):
        return '', None
    found = AI_CATEGORY_SUFFIX.search(raw_answer)
    if not found:
        return remove_model_thinking(raw_answer), None
    category = found.group(1).strip()
    clean_answer = remove_model_thinking(raw_answer[:found.start()])
    return clean_answer, category if category in VALID_AI_CATEGORIES else None


def dify_answer(query, conversation_id):
    payload = {'inputs': {}, 'query': query, 'response_mode': 'blocking',
               'conversation_id': conversation_id or '', 'user': DIFY_USER}
    req = urllib.request.Request(
        DIFY_API_BASE + '/chat-messages',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Authorization':'Bearer ' + DIFY_API_KEY,
                 'Content-Type':'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=55) as resp:
            result = json.loads(resp.read(1_000_000).decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            details = json.loads(e.read(2000).decode('utf-8')).get('message', '')
        except (UnicodeDecodeError, ValueError):
            details = ''
        raise ValueError('Dify 返回 HTTP ' + str(e.code) + (('：' + details[:160]) if details else '。请确认密钥、应用类型和模型配置。'))
    except (urllib.error.URLError, TimeoutError) as e:
        raise ValueError('无法连接 Dify：' + str(e)[:160])
    raw_answer = result.get('answer', '')
    if not raw_answer:
        raise ValueError('Dify 未返回 answer。请使用 Chatbot 或 Chatflow 应用，并选择非 Agent 的阻塞式接口。')
    answer, category = split_ai_answer(raw_answer)
    if not answer:
        raise ValueError('Dify 只返回了分类标记，未返回实际回答。请检查直接回复节点。')
    return {'answer':answer, 'matched':[], 'resolved':None, 'source':'dify',
            'category':category, 'category_source':'dify_classifier' if category else 'not_provided',
            'conversation_id':result.get('conversation_id', '')}



def dify_kb_ready():
    return bool(DIFY_KB_API_KEY and DIFY_DATASET_ID)


def sync_knowledge_to_dify(knowledge_id):
    """Create one Dify text document for a local KB entry.

    This is a demo-only one-way create sync. Dify indexing is asynchronous;
    '已提交' does NOT mean the content is already searchable.
    """
    if not dify_kb_ready():
        raise ValueError('尚未配置知识库密钥或 DIFY_DATASET_ID')
    try:
        UUID(DIFY_DATASET_ID)
    except (ValueError, AttributeError):
        raise ValueError('DIFY_DATASET_ID 应为知识库页面 URL 中的 UUID')
    with WRITE_LOCK, connect() as db:
        row = db.execute('SELECT * FROM knowledge WHERE id=?', (int(knowledge_id),)).fetchone()
        if not row:
            raise ValueError('本地知识不存在')
        synced = db.execute('SELECT * FROM knowledge_sync WHERE knowledge_id=?',(int(knowledge_id),)).fetchone()
        if synced and synced['document_id']:
            return {'status':'已提交', 'document_id':synced['document_id'], 'already_submitted':True}
        if synced and synced['status']=='提交中':
            raise ValueError('该知识正在提交中，请勿重复点击')
        db.execute('INSERT OR REPLACE INTO knowledge_sync (knowledge_id,document_id,status,error,submitted_at) VALUES (?,?,?,?,?)',
                   (int(knowledge_id),'','提交中','',''))
        db.commit()
        item=dict(row)
    payload = {
        'name': '智服AI-KB-%s-%s' % (knowledge_id,item['title']),
        'text': ('知识标题：'+item['title']+'\n知识分类：'+item['category']+
                 '\n关键词：'+item['keywords']+'\n操作指南：\n'+item['content']+
                 '\n（智服AI虚构企业演示资料，非真实企业制度）'),
        'indexing_technique':'high_quality',
        'process_rule':{'mode':'automatic'}
    }
    req=urllib.request.Request(
        DIFY_API_BASE+'/datasets/'+DIFY_DATASET_ID+'/document/create-by-text',
        data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
        headers={'Authorization':'Bearer '+DIFY_KB_API_KEY,'Content-Type':'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(req,timeout=35) as r:
            result=json.loads(r.read(200_000).decode('utf-8'))
        document_id=(result.get('document') or {}).get('id')
        if not document_id:
            raise ValueError('Dify 已响应但未提供 document.id，请到 Dify 检查，避免重复创建')
    except urllib.error.HTTPError as e:
        try:
            details = json.loads(e.read(2000).decode('utf-8')).get('message','')
        except (ValueError,UnicodeDecodeError):
            details = ''
        error='知识库 API HTTP %s：%s' % (e.code, (details[:140] or '检查知识库专用密钥、权限和索引配额'))
        with WRITE_LOCK,connect() as db:
            db.execute('UPDATE knowledge_sync SET status=?, error=? WHERE knowledge_id=?',('提交失败',error,int(knowledge_id)))
            db.commit()
        raise ValueError(error)
    except (urllib.error.URLError,TimeoutError,ValueError) as e:
        error='知识同步未确认：'+str(e)[:160]
        with WRITE_LOCK,connect() as db:
            db.execute('UPDATE knowledge_sync SET status=?,error=? WHERE knowledge_id=?',('提交失败',error,int(knowledge_id)))
            db.commit()
        raise ValueError(error)
    with WRITE_LOCK,connect() as db:
        db.execute('UPDATE knowledge_sync SET status=?,document_id=?,error=?,submitted_at=? WHERE knowledge_id=?',
                   ('已提交',document_id,'',now_str(),int(knowledge_id)))
        db.commit()
    return {'status':'已提交','document_id':document_id,'already_submitted':False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print('[请求] ' + fmt % args)

    def json_request(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise ValueError('Content-Length 不合法')
        if size < 0 or size > MAX_BODY:
            raise ValueError('请求内容过大（上限 50 KB）')
        try:
            return json.loads(self.rfile.read(size).decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise ValueError('JSON 请求格式错误')

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == '/api/health':
            return response_body(self, 200, {'ok':True, 'dify_connected':bool(DIFY_API_KEY),
                                               'mode':'dify' if DIFY_API_KEY else 'local',
                                               'note':'仅供本地演示，无真实身份认证',
                                               'knowledge_sync_configured':dify_kb_ready()})
        if p.path == '/api/summary':
            with connect() as db:
                counts = {r['status']:r['n'] for r in db.execute('SELECT status,COUNT(*) AS n FROM tickets GROUP BY status')}
                kb = db.execute('SELECT COUNT(*) FROM knowledge').fetchone()[0]
            return response_body(self, 200, {'total':sum(counts.values()), 'open':counts.get('待处理',0),
                    'progress':counts.get('处理中',0), 'done':counts.get('已解决',0), 'knowledge':kb})
        if p.path == '/api/knowledge':
            with connect() as db:
                rows = [dict(x) for x in db.execute('''SELECT k.*, COALESCE(s.status,'未同步') AS sync_status,
                COALESCE(s.error,'') AS sync_error, COALESCE(s.document_id,'') AS dify_document_id
                FROM knowledge k LEFT JOIN knowledge_sync s ON s.knowledge_id=k.id ORDER BY k.id DESC''')]
            return response_body(self, 200, {'items':rows})
        if p.path == '/api/tickets':
            with connect() as db:
                rows = [dict(x) for x in db.execute('SELECT * FROM tickets ORDER BY id DESC')]
            return response_body(self, 200, {'items':rows})
        if p.path in ('/', '/index.html'):
            return self.static('index.html', 'text/html; charset=utf-8')
        if p.path in ('/static/style.css','/static/app.js'):
            name = p.path.split('/')[-1]
            ct = 'text/css; charset=utf-8' if name.endswith('css') else 'application/javascript; charset=utf-8'
            return self.static(name, ct)
        return response_body(self, 404, {'error':'页面不存在'})

    def static(self, name, mime):
        data = (ROOT / 'static' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control','no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            body = self.json_request()
            if not isinstance(body, dict):
                raise ValueError('请求必须为 JSON 对象')
            if self.path == '/api/chat':
                query = clean_text(body.get('query'), 1000)
                if not query: raise ValueError('请输入问题')
                result = dify_answer(query, clean_text(body.get('conversation_id'), 60)) if DIFY_API_KEY else local_answer(query)
                return response_body(self, 200, result)
            if self.path == '/api/knowledge':
                title = clean_text(body.get('title'), 120)
                category = clean_text(body.get('category'), 40) or '其他问题'
                content = clean_text(body.get('content'), 8000)
                keywords = clean_text(body.get('keywords'), 200)
                if not title or not content: raise ValueError('标题和内容不能为空')
                with WRITE_LOCK, connect() as db:
                    cur = db.execute('INSERT INTO knowledge(category,title,content,keywords,created_at) VALUES(?,?,?,?,?)',
                                     (category,title,content,keywords,now_str()))
                    db.commit()
                new_id=cur.lastrowid
                sync_result={'status':'未配置'}
                if dify_kb_ready():
                    try:
                        sync_result=sync_knowledge_to_dify(new_id)
                    except ValueError as e:
                        sync_result={'status':'提交失败','error':str(e)}
                return response_body(self, 201, {'id':new_id,'success':True,'sync':sync_result})
            match=re.fullmatch(r'/api/knowledge/(\d+)/sync', self.path)
            if match:
                result=sync_knowledge_to_dify(int(match.group(1)))
                return response_body(self, 200, {'success':True, **result})
            if self.path == '/api/tickets':
                title = clean_text(body.get('title'), 120)
                description = clean_text(body.get('description'), 3000)
                category = clean_text(body.get('category'), 40) or categorize(title+description)
                priority = body.get('priority') if body.get('priority') in ('高','中','低') else '中'
                if not title or not description: raise ValueError('工单标题和描述不能为空')
                stamp = now_str()
                with WRITE_LOCK, connect() as db:
                    cur = db.execute('INSERT INTO tickets(title,description,category,priority,status,requester,assignee,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                               (title,description,category,priority,'待处理','演示员工','待分配',stamp,stamp))
                    db.commit()
                return response_body(self, 201, {'id':cur.lastrowid, 'success':True})
            return response_body(self, 404, {'error':'接口不存在'})
        except ValueError as e:
            # Dify's external error is treated as 502; validation as 400.
            status = 502 if str(e).startswith(('Dify','无法连接 Dify')) else 400
            return response_body(self, status, {'error':str(e)})
        except Exception as e:
            print('[服务错误]', repr(e))
            return response_body(self, 500, {'error':'服务器处理出错，请查看终端日志'})

    def do_PATCH(self):
        try:
            p = urlparse(self.path).path
            m = re.fullmatch(r'/api/tickets/(\d+)', p)
            if not m: return response_body(self, 404, {'error':'接口不存在'})
            body = self.json_request()
            if not isinstance(body, dict): raise ValueError('请求格式错误')
            status = body.get('status')
            if status not in ('待处理','处理中','已解决'): raise ValueError('非法工单状态')
            assignee = clean_text(body.get('assignee'), 60) or 'IT 支持'
            with WRITE_LOCK, connect() as db:
                cur = db.execute('UPDATE tickets SET status=?,assignee=?,updated_at=? WHERE id=?',
                                 (status,assignee,now_str(),int(m.group(1))))
                db.commit()
            if not cur.rowcount: return response_body(self, 404, {'error':'工单不存在'})
            return response_body(self, 200, {'success':True})
        except ValueError as e:
            return response_body(self, 400, {'error':str(e)})
        except Exception as e:
            print('[服务错误]', repr(e))
            return response_body(self, 500, {'error':'服务器处理出错'})


def main():
    init_db()
    print('\n'+'='*55)
    print('智服 AI · 企业智能 IT 服务与知识管理平台 (本地演示)')
    print('浏览器打开：http://127.0.0.1:' + str(PORT))
    print('问答引擎：' + ('Dify API（大模型）' if DIFY_API_KEY else '本地知识检索（非大模型）'))
    print('知识库写入：' + ('已配置（提交后由 Dify 异步索引）' if dify_kb_ready() else '未配置（仅本地保存）'))
    print('按 Ctrl+C 关闭服务。数据保存于：' + str(DB_PATH))
    print('='*55+'\n')
    server = ThreadingHTTPServer(('127.0.0.1',PORT), Handler)
    try: server.serve_forever()
    except KeyboardInterrupt: print('\n已停止。')
    finally: server.server_close()


if __name__ == '__main__':
    main()
