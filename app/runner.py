"""固定动作执行器；Playwright 实例只在 Worker 自己的线程中创建。"""
import os
import time
from pathlib import Path
from app.core import REF, VARIABLES, origin, relative_url, digest
from app.reports import build_reports

MESSAGES = {
    'PASS': '动作及本步骤断言通过（如有）',
    'FAIL': '预期断言未满足',
    'ERROR': '浏览器、定位、网络或配置异常',
    'BLOCKED': '前置步骤失败，未执行',
}

def locate(page, target):
    by, value = target['by'], target['value']
    if by == 'label':
        return page.get_by_label(value, exact=True)
    if by == 'role':
        return page.get_by_role(target['role'], name=value, exact=True)
    if by == 'text':
        return page.get_by_text(value, exact=True)
    return page.get_by_test_id(value)

def input_value(value):
    m = REF.fullmatch(value)
    if not m:
        return value
    name = m.group(1)
    if name not in VARIABLES:
        raise ValueError('Variable not allowed')
    return os.environ[name]

def execute_step(page, step, base):
    from playwright.sync_api import expect
    action = step['operation']
    name = action['action']
    if name == 'goto':
        response = page.goto(relative_url(base, action['value']),
                             wait_until='domcontentloaded')
        if response is not None and response.status >= 400:
            raise RuntimeError('Navigation HTTP error')
    elif name == 'fill':
        locate(page, action['target']).fill(input_value(action['value']))
    elif name == 'click':
        locate(page, action['target']).click()
    elif name == 'check':
        locate(page, action['target']).check()
    else:
        raise ValueError('Unknown action')
    expected = step['expected']
    if not expected:
        return
    if expected['type'] == 'visible':
        expect(locate(page, expected['target'])).to_be_visible(timeout=5000)
    elif expected['type'] == 'text':
        expect(locate(page, expected['target'])).to_have_text(expected['value'], timeout=5000)
    elif expected['type'] == 'url':
        expect(page).to_have_url(relative_url(base, expected['value']), timeout=5000)
    else:
        raise ValueError('Unknown assertion')

def run_steps(page, case, base, take_evidence, execute=execute_step):
    """可注入执行函数，允许无浏览器单元测试验证状态语义。"""
    rows, blocked = [], False
    for step in case['steps']:
        start = time.monotonic()
        status = 'BLOCKED' if blocked else 'PASS'
        if not blocked:
            try:
                execute(page, step, base)
            except AssertionError:
                status, blocked = 'FAIL', True
            except Exception:
                status, blocked = 'ERROR', True
        result = {'number': step['number'], 'row': step['row'], 'status': status,
                  'action': step['operation']['action'], 'expected': step['expected'],
                  'message': MESSAGES[status],
                  'seconds': round(time.monotonic() - start, 3)}
        if status in ('FAIL', 'ERROR'):
            # 截图失败不能覆盖原断言/执行状态。
            try:
                result['screenshot'] = take_evidence(page, step['number'])
            except Exception:
                result['evidence_warning'] = '截图采集失败'
        rows.append(result)
    states = {r['status'] for r in rows}
    state = 'ERROR' if 'ERROR' in states else 'FAIL' if 'FAIL' in states else 'PASS'
    return {'id': case['id'], 'module': case['module'], 'status': state, 'steps': rows}

def incomplete_case(case):
    return {'id': case['id'], 'module': case['module'], 'status': 'BLOCKED',
            'steps': [{'number': s['number'], 'row': s['row'], 'status': 'BLOCKED',
                       'action': s['operation']['action'], 'expected': s['expected'],
                       'message': '运行基础设施异常，未执行', 'seconds': 0}
                      for s in case['steps']]}

def run_plan(plan, run_id, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result = {'run_id': run_id, 'plan_hash': digest(plan), 'status': 'COMPLETED',
              'cases': [], 'error': ''}
    try:
        from playwright.sync_api import sync_playwright
        # 即使应用 API 是多线程，这些对象也不跨线程复用。
        with sync_playwright() as p:
            browser = p.chromium.launch(timeout=30000)
            try:
                allowed = origin(plan['base_url'])
                for case_no, case in enumerate(plan['cases'], 1):
                    context = browser.new_context(service_workers='block',
                                                  accept_downloads=False)
                    try:
                        def guard(route):
                            try:
                                permit = origin(route.request.url) == allowed
                            except (ValueError, TypeError):
                                permit = False
                            route.continue_() if permit else route.abort()
                        context.route('**/*', guard)
                        page = context.new_page()
                        page.on('dialog', lambda dialog: dialog.dismiss())
                        page.set_default_timeout(5000)
                        page.set_default_navigation_timeout(15000)
                        def screenshot(current, step_no):
                            filename = f'case-{case_no}-step-{step_no}.png'
                            current.screenshot(path=str(folder / filename),
                                full_page=False, timeout=5000,
                                mask=[current.locator('input,textarea,[contenteditable]')])
                            return filename
                        result['cases'].append(run_steps(page, case,
                                                         plan['base_url'], screenshot))
                    finally:
                        context.close()
            finally:
                browser.close()
    except Exception:
        result['status'] = 'ERROR'
        result['error'] = '浏览器未安装、启动失败或运行基础设施异常；请检查本机环境'
        for case in plan['cases'][len(result['cases']):]:
            result['cases'].append(incomplete_case(case))
    build_reports(folder, result)
    return result
