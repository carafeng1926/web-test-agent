"""CI 门禁：报告生成成功不代表用例通过。"""
import json
import sys
from pathlib import Path

def main():
    result=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    ok=(result['status']=='COMPLETED' and bool(result['cases']) and
        all(c['status']=='PASS' for c in result['cases']))
    print('PASS' if ok else 'NOT_PASS')
    raise SystemExit(0 if ok else 1)

if __name__=='__main__': main()
