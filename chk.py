import ast, sys
files = ['services/ai_lecture_generation_service.py','services/pptx_service.py','routes/lecture.py','schemas.py','main.py']
ok = True
for f in files:
    try:
        ast.parse(open(f,encoding='utf-8').read())
        print('OK', f)
    except SyntaxError as e:
        print('ERROR', f, e)
        ok = False
print('ALL OK' if ok else 'ERRORS FOUND')
