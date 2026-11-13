"""Read-only documentation and AST inspection."""
import ast
import os
import re
from pathlib import Path
from .phrases import BANKSTATEMENTEXTRACTION, NOBANKSTATEMENTEXTRACTION, GENERIC_NAMES


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def prose(text):
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if match:
            fence = match[1]
        else:
            lines.append(line)
    return '\n'.join(lines)


def claims(text):
    positive = negative = False
    for paragraph in re.split(r'\n\s*\n', prose(text)):
        paragraph = normalize(paragraph)
        for phrase in sorted(NOBANKSTATEMENTEXTRACTION, key=lambda p: (-len(p), p)):
            paragraph, count = re.subn(r'\b' + re.escape(phrase) + r'\b', ' ', paragraph)
            negative |= bool(count)
        positive |= any(re.search(r'\b' + re.escape(p) + r'\b', paragraph) for p in sorted(BANKSTATEMENTEXTRACTION, key=lambda p: (-len(p), p)))
    return bool(positive), bool(negative)


def evidence(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    nodes = list(ast.walk(tree))
    shadows = {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    bindings = {}
    imports = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
                bindings[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            for alias in node.names:
                bindings[alias.asname or alias.name] = node.module + '.' + alias.name
                imports.add(node.module + '.' + alias.name)
    def resolve(node, seen=None):
        if isinstance(node, ast.Name):
            if node.id in shadows:
                return ''
            value = bindings.get(node.id, '')
            if isinstance(value, str):
                return value
            seen = set() if seen is None else seen
            if node.id in seen:
                return ''
            return resolve(value, seen | {node.id})
        if isinstance(node, ast.Attribute):
            base = resolve(node.value, seen)
            return base + '.' + node.attr if base else ''
        return ''
    for node in nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        bindings[name.id] = node.value
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars:
                    for name in ast.walk(item.optional_vars):
                        if isinstance(name, ast.Name):
                            bindings[name.id] = item.context_expr
    azure_gate = any(i == m or i.startswith(m + '.') for i in imports for m in ('azure.ai.formrecognizer', 'azure.ai.documentintelligence'))
    veryfi_gate = any(i == 'veryfi' or i.startswith('veryfi.') for i in imports)
    azure_client = veryfi_client = azure_call = veryfi_call = False
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        resolved = resolve(func)
        attr = func.attr if isinstance(func, ast.Attribute) else ''
        if isinstance(func, ast.Name):
            if resolved.split('.')[-1] in GENERIC_NAMES and resolved.split('.')[-1] not in shadows:
                return True
        elif attr in GENERIC_NAMES and attr not in shadows and not (isinstance(func.value, ast.Name) and func.value.id in shadows):
            return True
        if isinstance(func, ast.Name):
            azure_client |= resolved in ('azure.ai.formrecognizer.DocumentAnalysisClient', 'azure.ai.documentintelligence.DocumentIntelligenceClient')
            veryfi_client |= resolved == 'veryfi.Client'
        elif attr not in shadows:
            chain = func.value
            while isinstance(chain, ast.Attribute):
                chain = chain.value
            azure_client |= attr in ('DocumentAnalysisClient', 'DocumentIntelligenceClient') and isinstance(chain, ast.Name) and resolve(chain).split('.')[0] == 'azure'
            veryfi_client |= attr == 'Client' and isinstance(func.value, ast.Name) and func.value.id == 'veryfi' and resolve(func.value) == 'veryfi'
        if attr in shadows or (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in shadows):
            continue
        if attr in ('begin_analyze_document', 'begin_analyze_document_from_url'):
            args = ([node.args[0]] if node.args else []) + [k.value for k in node.keywords if k.arg == 'model_id']
            azure_call |= any(isinstance(a, ast.Constant) and a.value == 'prebuilt-bankStatement.us' for a in args)
        veryfi_call |= attr in ('process_bank_statement_document', 'process_bank_statement_document_url')
    return bool((azure_gate and azure_client and azure_call) or (veryfi_gate and veryfi_client and veryfi_call))


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir():
        raise OSError('Repository must be a readable directory')
    positive, negative, production, tests = [], [], [], []
    def ignored(rel):
        return any(rel == p.strip('/') or rel.startswith(p.strip('/') + '/') for p in ignore)
    def walk_error(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink() and not ignored((Path(directory) / d).relative_to(root).as_posix()))
        for filename in sorted(files):
            path = Path(directory) / filename
            rel = path.relative_to(root)
            if path.is_symlink() or ignored(rel.as_posix()):
                continue
            if rel.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in rel.parts[:-1]):
                yes, no = claims(path.read_text(encoding='utf-8'))
                if yes: positive.append(rel.as_posix())
                if no: negative.append(rel.as_posix())
            if path.suffix == '.py' and not set(rel.parts[:-1]) & {'fixtures', 'docs', 'examples'}:
                if evidence(path.read_text(encoding='utf-8')):
                    target = tests if 'tests' in rel.parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py') else production
                    target.append(rel.as_posix())
    findings = []
    if positive and not production:
        findings.append(dict(id='documented-bank-statement-extraction-claim-false', severity='MEDIUM' if tests else 'HIGH', message='Documented capability has only test evidence.' if tests else 'Documented capability has no production evidence.', docs=positive))
    if negative and production:
        findings.append(dict(id='documented-no-bank-statement-extraction-claim-false', severity='HIGH', message='Documented denial contradicts production evidence.', docs=negative))
    return dict(verdict='FAIL' if findings else 'PASS', findings=findings, production_evidence=production, test_evidence=tests)
