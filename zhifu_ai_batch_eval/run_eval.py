#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智服 AI V4 - 独立、无第三方依赖的真实 Dify 批量评测脚本。
仅调用 /api/health 与 /api/chat，不调用工单/知识写入 API。
Python 3.9+。用法：python3 run_eval.py；全部：python3 run_eval.py --all。
"""
import argparse
import csv
import html
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / 'testcases.json'
FIRST_FIVE = ('T03', 'T05', 'T18', 'T22', 'T25')
CATEGORIES = ('办公网络', '账号权限', '办公软件', '办公设备', '其他问题')


def read_cases():
    items = json.loads(CASES_PATH.read_text(encoding='utf-8'))
    ids = [x['id'] for x in items]
    if len(items) != 30 or len(set(ids)) != len(ids):
        raise ValueError('测试用例应为 30 条且编号唯一，请检查 testcases.json')
    return items


def parse_turns(case):
    q = case['question'].strip()
    if case['mode'] != '同一会话连续两轮':
        return [q]
    m = re.fullmatch(r'第\s*1\s*轮[：:]\s*(.+?)\s*第\s*2\s*轮[：:]\s*(.+)', q, re.S)
    if not m:
        raise ValueError('多轮题格式不符合“第 1 轮：... 第 2 轮：...”：' + case['id'])
    return [m.group(1).strip(), m.group(2).strip()]


def request_json(url, payload=None, timeout=75):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'}, method='GET' if payload is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(2_000_000).decode('utf-8')
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read(1200).decode('utf-8', errors='replace')
        try:
            body = json.loads(body).get('error', body)
        except ValueError:
            pass
        raise RuntimeError('HTTP %s：%s' % (e.code, str(body)[:350])) from e
    except urllib.error.URLError as e:
        raise RuntimeError('网络不可达：' + str(e.reason)) from e
    except (TimeoutError, OSError) as e:
        raise RuntimeError('请求超时/连接中断：' + str(e)) from e
    except ValueError as e:
        raise RuntimeError('API 返回的不是合法 JSON：' + str(e)) from e


def read_latest_records(path):
    d = {}
    if not path.exists():
        return d
    with path.open('r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if isinstance(record, dict) and record.get('id'):
                    d[record['id']] = record
            except json.JSONDecodeError:
                print('警告：忽略不完整的历史记录第 %s 行' % i)
    return d


def run_one(case, base, timeout):
    start_at = datetime.now().astimezone().isoformat(timespec='seconds')
    conversation_id = ''
    turns = []
    fatal_error = ''
    for index, question in enumerate(parse_turns(case), start=1):
        started = time.monotonic()
        answer, category, source, error = '', '', '', ''
        try:
            response = request_json(base + '/api/chat', {'query':question, 'conversation_id':conversation_id}, timeout)
            if not isinstance(response, dict):
                raise RuntimeError('接口返回的数据结构错误')
            answer = response.get('answer') or ''
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError('AI 未返回可用 answer')
            category = response.get('category') or ''
            source = response.get('source') or ''
            if source != 'dify':
                raise RuntimeError('回答来源不是 Dify（source=%r），不能计入真实 AI 评测' % source)
            if response.get('conversation_id'):
                conversation_id = response['conversation_id']
            elif index < len(parse_turns(case)):
                raise RuntimeError('Dify 未返回 conversation_id，无法保证后续轮次共享上下文')
        except Exception as e:
            error = str(e)[:400]
            fatal_error = error
        seconds = round(time.monotonic() - started, 3)
        turns.append({'turn':index, 'question':question, 'answer':answer, 'category':category,
                      'source':source, 'elapsed_seconds':seconds, 'error':error})
        if error:
            break
    ok = not fatal_error and len(turns) == len(parse_turns(case))
    final = turns[-1] if turns else {}
    predicted = final.get('category') or ''
    return {'id':case['id'], 'type':case['type'], 'question':case['question'],
            'expected_category':case['expected_category'], 'reference_document':case['reference_document'],
            'coverage':case['coverage'], 'expected_keypoints':case['expected_keypoints'],
            'avoid':case['avoid'], 'mode':case['mode'], 'finished_at':start_at,
            'status':'成功' if ok else '失败', 'predicted_category':predicted,
            'category_correct':bool(ok and predicted == case['expected_category']),
            'elapsed_seconds':round(sum(t['elapsed_seconds'] for t in turns),3),
            'request_count':len(turns), 'answer':final.get('answer',''),
            'error':fatal_error, 'turns':turns, 'answer_source':final.get('source',''),
            # /api/chat does not expose Dify retrieval references.
            'retrieval_top1':'', 'retrieval_top3':'', 'manual_quality_score':'', 'manual_notes':''}


def export_csv(path, headers, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer=csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def col_letter(n):
    s=''
    while n:
        n, a = divmod(n-1,26)
        s = chr(65+a)+s
    return s


def safe_xml_text(s):
    s = str(s if s is not None else '')
    s = ''.join(ch if ch in '\t\n\r' or ord(ch)>=32 else ' ' for ch in s)
    return escape(s[:32000], {'"':'&quot;', "'":'&apos;'})


def sheet_xml(rows, widths, freeze=1, title_row=0, filters=False):
    """Pure-stdlib OOXML report for Macs without extra Python packages."""
    sh = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
          '<sheetViews><sheetView workbookViewId="0">',
          '<pane ySplit="%d" topLeftCell="A%d" activePane="bottomLeft" state="frozen"/>' % (freeze,freeze+1) if freeze else '',
          '</sheetView></sheetViews>']
    sh.append('<cols>')
    for i, w in enumerate(widths, 1):
        sh.append('<col min="%d" max="%d" width="%.1f" customWidth="1"/>' % (i,i,w))
    sh.append('</cols><sheetData>')
    for ridx, row in enumerate(rows, 1):
        if title_row and ridx==title_row:
            style = 2
        elif ridx == 1 or (title_row and ridx==title_row+1):
            style = 1
        else:
            style = 6 if ridx % 2 else 0
        height = 36 if style==1 else 28 if style==2 else 42 if len(rows)>3 and ridx>1 else 25
        sh.append('<row r="%d" ht="%d" customHeight="1">' % (ridx,height))
        for idx,val in enumerate(row,1):
            if val is None:
                continue
            address = '%s%d' % (col_letter(idx),ridx)
            sty = style
            if style not in (1,2) and isinstance(val,str) and val in ('失败','错误','不正确'):
                sty=4
            elif style not in (1,2) and isinstance(val,str) and val in ('成功','正确'):
                sty=3
            if isinstance(val,(int,float)) and not isinstance(val,bool):
                sh.append('<c r="%s" s="%d"><v>%s</v></c>' % (address,sty,val))
            else:
                sh.append('<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (address,sty,safe_xml_text(val)))
        sh.append('</row>')
    sh.append('</sheetData>')
    if filters and len(rows)>1:
        sh.append('<autoFilter ref="A1:%s%d"/>' %(col_letter(max(len(x) for x in rows)),len(rows)))
    sh.append('</worksheet>')
    return ''.join(sh)


def write_xlsx(path, sheets):
    """A self-contained XLSX writer: no pip installs, no dependency on Excel/Numbers."""
    styles='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="3"><font><sz val="11"/><name val="PingFang SC"/><color rgb="FF263755"/></font><font><b/><sz val="11"/><name val="PingFang SC"/><color rgb="FFFFFFFF"/></font><font><b/><sz val="16"/><name val="PingFang SC"/><color rgb="FF17253F"/></font></fonts>
<fills count="6"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF17253F"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEAF0FF"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE5F7EE"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFDE8E7"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="7"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf><xf numFmtId="0" fontId="0" fillId="4" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="5" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''
    names=[s[0] for s in sheets]
    wbs='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
    for i,name in enumerate(names,1):
        wbs += '<sheet name="%s" sheetId="%d" r:id="rId%d"/>' %(safe_xml_text(name),i,i)
    wbs+='</sheets></workbook>'
    rel='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    for i in range(1,len(names)+1):
        rel+='<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' %(i,i)
    rel+='<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'%(len(names)+1)
    types='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    for i in range(1,len(names)+1):
        types+='<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'%i
    types+='</Types>'
    with ZipFile(path,'w',ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',types)
        z.writestr('_rels/.rels','<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',wbs)
        z.writestr('xl/_rels/workbook.xml.rels',rel)
        z.writestr('xl/styles.xml',styles)
        for i,(_name,rows,widths) in enumerate(sheets,1):
            z.writestr('xl/worksheets/sheet%d.xml'%i, sheet_xml(rows,widths,freeze=1,filters=i==2))


def export_reports(cases, latest, directory, mode):
    directory.mkdir(exist_ok=True, parents=True)
    records=[latest.get(c['id'],{}) for c in cases]
    tested=[x for x in records if x]
    successful=[x for x in tested if x.get('status')=='成功' and x.get('answer_source')=='dify']
    correct=[x for x in successful if x.get('category_correct')]
    failures=[x for x in tested if x.get('status')!='成功']
    avg=round(statistics.mean(x['elapsed_seconds'] for x in successful),2) if successful else None
    rate=round(len(correct)/len(successful)*100,1) if successful else None
    successrate=round(len(successful)/len(tested)*100,1) if tested else None
    metrics=[('测试用例总数',len(cases)),('已实际测试',len(tested)),('请求成功题数',len(successful)),
             ('请求成功率（按已测）',('%s%%'%successrate) if successrate is not None else '待测试'),
             ('分类正确题数',len(correct)),('分类准确率（按成功题）',('%s%%'%rate) if rate is not None else '待测试'),
             ('平均每题响应时间/秒',avg if avg is not None else '待测试'),
             ('失败题数',len(failures)),('RAG Top3 命中率','未采集：/api/chat 不返回检索节点片段'),
             ('平均回答质量','待人工评分'),('结果类型','真实 Dify 接口测试；未测试项不计入准确率')]
    cols=['编号','测试类型','问题','预期分类','模型分类','分类判定','请求状态','回答来源',
          '响应时间（秒）','请求轮数','知识覆盖','目标文档','回答摘要（非全文）',
          '人工质量（0-10）','Top3 命中（人工核实）','人工分析备注','错误信息']
    rr=[]
    for c in cases:
        r=latest.get(c['id'],{})
        status=r.get('status','未测试')
        classification=('正确' if r.get('category_correct') else '不正确') if status=='成功' else ('—' if not r else '失败未评')
        rr.append([c['id'],c['type'],c['question'],c['expected_category'],r.get('predicted_category',''),
                   classification,status,r.get('answer_source',''),r.get('elapsed_seconds',''),
                   r.get('request_count',''),c.get('coverage',''),c.get('reference_document',''),
                   (r.get('answer','')[:230] + ('…' if len(r.get('answer',''))>230 else '')),
                   '', '', '',r.get('error','')])
    lines=[['编号','轮次','该轮问题','模型分类','来源','耗时（秒）','该轮AI回答全文','错误']]
    for c in cases:
        r=latest.get(c['id'],{})
        for turn in r.get('turns',[]):
            lines.append([c['id'],turn['turn'],turn['question'],turn['category'],turn['source'],
                          turn['elapsed_seconds'],turn['answer'],turn['error']])
    notes=[['评测说明','内容'],
           ['测试入口','V4 /api/chat；调用本地后端转发至 Dify 的真实 API'],
           ['会话隔离','每题新建 conversation_id；T28~T30 在同一题中复用 conversation_id'],
           ['首批试运行','T03、T05、T18、T22、T25（不重复运行已成功题目）'],
           ['分类准确率','在请求成功的题目中，按模型输出分类与预期分类完全一致的比例计算；未返回分类视为错误'],
           ['请求成功率','成功题数/已实际测试题数；失败题目会保留错误原因'],
           ['时间统计','每题所有轮次合计响应时间；多轮题耗时与单轮不完全可比'],
           ['RAG 检索','本系统 /api/chat 返回 matched=[]（Dify模式），无法自动证明 Top1/Top3 召回；需要从 Dify 检索节点或召回测试人工核实'],
           ['回答质量/幻觉','必须人工依据知识原文给分；自动化不把关键词命中冒充事实准确性'],
           ['演示知识','仅作为测试样例，不代表任何真实企业规则/配置'],
           ['数据安全','本地报告包含问题和完整回答，不包含 Dify API 密钥；不要上传真实公司内部敏感信息'],
           ['评测不是生产统计','样本来自有限 30 条测试集，不能泛化为所有真实企业场景的准确率']]
    summary=[['智服 AI｜30 题自动化评测概览','结果'],*metrics,
             ['',''],['分类维度','已成功题数','分类正确','分类准确率']]
    for cat in CATEGORIES:
        group=[x for x in successful if x['expected_category']==cat]
        corr=sum(bool(x.get('category_correct')) for x in group)
        summary.append([cat,len(group),corr,'%s%%'%round(corr/len(group)*100,1) if group else '未测试'])
    summary += [['',''],['测试类型','已成功题数','分类正确','分类准确率']]
    types=sorted(set(c['type'] for c in cases))
    for kind in types:
        group=[x for x in successful if x['type']==kind]
        corr=sum(bool(x.get('category_correct')) for x in group)
        summary.append([kind,len(group),corr,'%s%%'%round(corr/len(group)*100,1) if group else '未测试'])
    xlsx=directory/'智服AI_批量评测结果.xlsx'
    write_xlsx(xlsx,[('评测概览',summary,[38,44,18,25]),('逐题结果',[cols]+rr,[11,17,56,16,16,14,15,14,18,14,13,51,65,21,23,41,51]),
                     ('AI回答全文',lines,[11,9,56,16,13,18,110,45]),('评分说明',notes,[29,115])])
    export_csv(directory/'逐题结果_Excel可打开.csv',cols,rr)
    export_csv(directory/'AI回答全文_Excel可打开.csv',lines[0],lines[1:])
    (directory/'metrics.json').write_text(json.dumps({'total':len(cases),'tested':len(tested),'success':len(successful),
                    'correct':len(correct),'class_accuracy_pct':rate,'success_rate_pct':successrate,
                    'avg_case_seconds':avg,'retrieval_top3_rate':None,'quality_score':None},ensure_ascii=False,indent=2), encoding='utf-8')
    cards=''.join('<div class="card"><span>%s</span><strong>%s</strong></div>'%(html.escape(label),html.escape(str(value))) for label,value in metrics[:8])
    table=''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%.2f</td></tr>' %(
             html.escape(c['id']),html.escape(c['type']),html.escape(latest.get(c['id'],{}).get('status','未测试')),
             html.escape(c['expected_category']),html.escape(latest.get(c['id'],{}).get('predicted_category','—')),
             float(latest.get(c['id'],{}).get('elapsed_seconds',0))) for c in cases)
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>智服 AI 自动化评测报告</title><style>
    *{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;background:#f5f7fc;color:#20304b;margin:0;padding:40px;line-height:1.6}
    h1{margin:0 0 9px}p{color:#72819c}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:25px 0}.card{border:1px solid #e4eaf4;border-radius:15px;background:#fff;padding:20px}
    .card span{display:block;font-size:13px;color:#7587a6}.card strong{display:block;font-size:26px;color:#5276ea;margin-top:8px}.panel{background:#fff;border-radius:16px;padding:20px;border:1px solid #e6eaf4}
    table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;border-bottom:1px solid #ecf0f6;padding:12px}th{background:#eff3fa}small{color:#7d8eaa}</style>
    <h1>智服 AI｜30 题自动评测报告</h1><p>本地 V4 /api/chat 调用 · 只采集客观结果，不自动宣称 RAG 召回或回答质量</p>
    <div class="grid">'''+cards+'''</div><div class="panel"><h2>逐题结果</h2><table><tr><th>编号</th><th>测试类型</th><th>请求状态</th><th>预期分类</th><th>实际分类</th><th>耗时（秒）</th></tr>'''+table+'''</table></div>
    <p><small>完整回答及错误详情参见 Excel 的「AI回答全文」页。无知识答案、事实准确性和安全性需人工复核。</small></p></html>'''
    (directory/'评测汇总.html').write_text(document,encoding='utf-8')
    return xlsx, len(tested), len(successful), rate


def main(argv=None):
    parser=argparse.ArgumentParser(description='智服 AI｜批量 RAG / 分类效果评测（仅调用 /api/chat）')
    g=parser.add_mutually_exclusive_group()
    g.add_argument('--all', action='store_true',help='运行全部 30 题（自动跳过已成功题目）')
    g.add_argument('--ids',help='只运行指定题目，例如 --ids T18,T22')
    g.add_argument('--dry-run',action='store_true',help='只显示拟运行的题目，不请求 API')
    parser.add_argument('--base-url',default=os.environ.get('ZHIFU_EVAL_BASE_URL','http://127.0.0.1:8765'),help='智服AI本地服务地址')
    parser.add_argument('--timeout',type=int,default=75,help='单次接口超时秒数，默认75')
    parser.add_argument('--delay',type=float,default=1.5,help='请求间隔秒数，默认1.5')
    parser.add_argument('--redo',action='store_true',help='重新运行选中的题目（可能额外消耗额度）')
    parser.add_argument('--allow-local',action='store_true',help='仅用于本地脚本测试，不建议用于真实AI评测')
    args=parser.parse_args(argv)
    if args.delay<0 or args.timeout<1:
        parser.error('timeout 必须大于 0，delay 不得为负数')
    cases=read_cases()
    byid={c['id']:c for c in cases}
    if args.ids:
        chosen=[x.strip().upper() for x in args.ids.split(',') if x.strip()]
        invalid=[x for x in chosen if x not in byid]
        if invalid:parser.error('未知题号：'+', '.join(invalid))
        selected=[byid[x] for x in dict.fromkeys(chosen)]
    else:
        selected=cases if args.all else [byid[x] for x in FIRST_FIVE]
    folder=ROOT/'eval_output'
    records_file=folder/'运行历史.jsonl'
    latest=read_latest_records(records_file)
    todo=[c for c in selected if args.redo or not (latest.get(c['id'],{}).get('status')=='成功' and latest[c['id']].get('answer_source')=='dify')]
    print('智服 AI｜AI 批量效果评测\n选择 %d 题，已完成并自动跳过 %d 题，待执行 %d 题。' %(len(selected),len(selected)-len(todo),len(todo)))
    if args.dry_run:
        for c in todo:print('%s [%s] %s' %(c['id'],c['expected_category'],c['question'].replace('\n',' / ')))
        return 0
    base=args.base_url.rstrip('/')
    if base.startswith('https://'):
        print('注意：通过 HTTPS 调用自行配置的后端 URL。')
    if not base.startswith(('http://','https://')):
        parser.error('--base-url 必须以 http:// 或 https:// 开头')
    if not todo:
        xlsx,n,s,acc=export_reports(cases,latest,folder,'dify')
        print('没有待执行的题目；已刷新报告：'+str(xlsx))
        return 0
    try:
        health=request_json(base+'/api/health',timeout=10)
    except Exception as e:
        print('❌ 智服 AI 服务不可访问：'+str(e))
        print('请先启动新版项目：cd ~/Downloads/zhifu_ai_v4_figma && python3 app.py')
        return 2
    mode=health.get('mode') if isinstance(health,dict) else None
    if not health.get('ok') or (mode!='dify' and not args.allow_local):
        print('❌ 目前检测到问答模式：%s；请先启用 Dify 后再批量评测。' % mode)
        print('你需要先启动配置好 DIFY_API_KEY 的 V4 后端；无需将密钥提供给评测脚本。')
        return 3
    if mode!='dify':
        print('注意：本地模式不会作为 Dify 成功题计数，仅用于检测接口。')
    else:
        print('✅ 服务检查通过：当前模式为 Dify（会消耗你的模型 API 额度）。')
    folder.mkdir(exist_ok=True,parents=True)
    stop=False
    with records_file.open('a',encoding='utf-8') as history:
        for i,c in enumerate(todo,1):
            print('[%d/%d] %s %s' %(i,len(todo),c['id'],c['question'].split('\n')[0][:46]),flush=True)
            record=run_one(c,base,args.timeout)
            history.write(json.dumps(record,ensure_ascii=False)+'\n')
            history.flush()
            latest[c['id']]=record
            mark='✅' if record['status']=='成功' else '❌'
            cat=record['predicted_category'] or '未返回'
            print('  %s %s｜分类：%s（预期：%s）｜用时：%.2f 秒%s' %(
                mark,record['status'],cat,c['expected_category'],record['elapsed_seconds'],
                ('｜错误：'+record['error']) if record['error'] else ''),flush=True)
            if record['error'] and re.search(r'HTTP (401|402|403|429)|配额|余额|quota|rate.limit|insufficient',record['error'],re.I):
                print('⚠️ 可能遇到密钥/余额/额度限制，已停止后续题目以免重复请求。')
                stop=True
            if stop:break
            if i<len(todo) and args.delay: time.sleep(args.delay)
    xlsx,n,s,acc=export_reports(cases,latest,folder,mode)
    print('\n评测输出：%s\nHTML 预览：%s\n历史记录：%s' %(xlsx,folder/'评测汇总.html',records_file))
    print('已测 %d/30，成功 %d，分类准确率 %s。'%(n,s, ('%.1f%%'%acc if acc is not None else '待测试')))
    print('注意：RAG Top3 命中和回答质量仍须在 Dify / 人工复核。')
    return 0 if not stop else 4


if __name__=='__main__':
    try:sys.exit(main())
    except KeyboardInterrupt:
        print('\n已手动中止。之前完成的测试会保存，下次可续跑。')
        sys.exit(130)
