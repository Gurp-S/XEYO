import re
c = open('memory_stack_eval.py', encoding='utf-8').read()
m = re.search(r'_A3_RENDER_JS = r"""(.+?)"""', c, re.S)
if m:
    open('_a3_check.js', 'w', encoding='utf-8').write(m.group(1))
    print('JS extracted')
else:
    print('not found')