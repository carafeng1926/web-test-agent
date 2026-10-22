import json
from pathlib import Path
from openpyxl import Workbook
from app.core import HEADERS

def sample_rows():
    def j(v): return json.dumps(v, ensure_ascii=False)
    def action(name, value=None, target=None):
        v = {'action':name}
        if value is not None: v['value'] = value
        if target is not None: v['target'] = target
        return j(v)
    def target(by, value, **kw): return {'by':by, 'value':value, **kw}
    rows = []
    for cid, expected in [('LOGIN_PASS','欢迎回来'), ('LOGIN_FAIL','这是故意错误的期望')]:
        rows.extend([
            [cid,'登录',1,action('goto','/demo'),None],
            [cid,'登录',2,action('fill','demo',target('label','用户名')),None],
            [cid,'登录',3,action('fill','demo',target('label','密码')),None],
            [cid,'登录',4,action('click',target=target('role','登录',role='button')),
             j({'type':'text','target':target('text','欢迎回来'),'value':expected})],
        ])
    rows.extend([
        ['LOCATOR_ERROR','定位',1,action('goto','/demo'),None],
        ['LOCATOR_ERROR','定位',2,action('click',target=target('testid','missing-button')),None],
        ['LOCATOR_ERROR','定位',3,action('click',target=target('role','登录',role='button')),
         j({'type':'visible','target':target('text','登录失败')})],
    ])
    return rows

def main():
    wb=Workbook(); ws=wb.active; ws.title='测试用例'
    ws.append(HEADERS)
    for row in sample_rows(): ws.append(row)
    ws.column_dimensions['A'].width=22
    ws.column_dimensions['B'].width=14
    ws.column_dimensions['D'].width=70
    ws.column_dimensions['E'].width=70
    Path('examples').mkdir(exist_ok=True)
    wb.save('examples/demo.xlsx')
    print('示例表格已生成：examples/demo.xlsx')

if __name__ == '__main__': main()
