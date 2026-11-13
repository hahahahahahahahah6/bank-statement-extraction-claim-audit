import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from bank_statement_extraction_claim_audit.audit import audit, claims, evidence
from bank_statement_extraction_claim_audit.phrases import BANKSTATEMENTEXTRACTION, NOBANKSTATEMENTEXTRACTION, GENERIC_NAMES
from bank_statement_extraction_claim_audit.__main__ import main

class AuditTests(unittest.TestCase):
    def repo(self, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return root

    def cli(self, root, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['audit', str(root), *args])
        return code, output.getvalue()

    def test_azure_submodule_from_import(self):
        self.assertTrue(evidence('from azure.ai import formrecognizer as az\nc=az.DocumentAnalysisClient()\nc.begin_analyze_document("prebuilt-bankStatement.us")'))

    def test_azure_split_module(self):
        root = self.repo({'README.md': 'statement extraction', 'a.py': 'from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()', 'b.py': 'c.begin_analyze_document("prebuilt-bankStatement.us")'})
        self.assertEqual(self.cli(root)[0], 2)

    def test_async_with_binding(self):
        self.assertFalse(evidence('from library import extract_statement\nasync def run():\n async with other() as extract_statement:\n  extract_statement()'))

    def test_phrase_oracle(self):
        self.assertEqual(BANKSTATEMENTEXTRACTION, EXPECTED_POSITIVE)
        self.assertEqual(NOBANKSTATEMENTEXTRACTION, EXPECTED_NEGATIVE)
        self.assertEqual(GENERIC_NAMES, EXPECTED_GENERIC)
        self.assertEqual(len(set(GENERIC_NAMES)), 24)

    def test_bad_high_json(self):
        root = self.repo({'README.md': 'Extract bank statements.'})
        code, output = self.cli(root, '--json')
        data = json.loads(output)
        self.assertEqual(code, 2)
        self.assertEqual(data['verdict'], 'FAIL')
        self.assertEqual(data['findings'][0]['id'], 'documented-bank-statement-extraction-claim-false')
        self.assertEqual(data['findings'][0]['severity'], 'HIGH')
        self.assertTrue(data['findings'][0]['message'])

    def test_good(self):
        root = self.repo({'README.md': 'Extract bank statements.', 'app.py': 'x.extract_bank_statement()'})
        self.assertEqual(self.cli(root)[0], 0)
        self.assertEqual(audit(root)['verdict'], 'PASS')

    def test_denial(self):
        root = self.repo({'README.md': 'Does not extract bank statements.', 'app.py': 'x.parse_statement()'})
        self.assertEqual(self.cli(root)[0], 2)
        self.assertEqual(audit(root)['findings'][0]['id'], 'documented-no-bank-statement-extraction-claim-false')
        self.assertEqual(audit(root)['findings'][0]['severity'], 'HIGH')

    def test_no_source_denial(self):
        self.assertEqual(audit(self.repo({'README.md': 'No bank statement extraction.'}))['verdict'], 'PASS')

    def test_no_claim(self):
        self.assertEqual(audit(self.repo({'README.md': 'Hello', 'a.py': 'x.parse_statement()'}))['verdict'], 'PASS')

    def test_test_only(self):
        for name in ('tests/a.py', 'test_a.py', 'a_test.py'):
            with self.subTest(name=name):
                root = self.repo({'README.md': 'Statement extraction', name: 'x.parse_statement()'})
                self.assertEqual(self.cli(root)[0], 0)
                self.assertEqual(audit(root)['findings'][0]['severity'], 'MEDIUM')
                self.assertEqual(self.cli(root, '--fail-on', 'medium')[0], 2)

    def test_document_matching(self):
        self.assertEqual(claims("Doesn't extract bank statements"), (False, True))
        self.assertEqual(claims('`extract bank statements`'), (True, False))
        self.assertEqual(claims('extract-bank-statements'), (True, False))
        self.assertEqual(claims('preextract statementsx'), (False, False))
        for fence in ('```', '~~~', '   ````'):
            self.assertEqual(claims(fence+'\nextract bank statements\n'+fence), (False, False))
        self.assertEqual(claims('does not extract bank statements\n\nextract bank statements'), (True, True))

    def test_docs_scope(self):
        root = self.repo({'other.md': 'statement extraction', 'nested/README.md': 'statement extraction'})
        self.assertEqual(audit(root)['verdict'], 'PASS')
        (root/'nested/docs').mkdir()
        (root/'nested/docs/a.md').write_text('statement extraction')
        self.assertEqual(audit(root)['verdict'], 'FAIL')

    def test_exclusions_and_ignore(self):
        for name in ('fixtures/a.py', 'docs/a.py', 'examples/a.py'):
            root = self.repo({'README.md': 'statement extraction', name: 'x.parse_statement()'})
            self.assertEqual(audit(root)['findings'][0]['severity'], 'HIGH')
        root = self.repo({'README.md': 'statement extraction', 'vendor/a.py': 'x.parse_statement()'})
        self.assertEqual(self.cli(root, '--ignore', 'vendor')[0], 2)
        self.assertEqual(self.cli(root, '--ignore', 'ven')[0], 0)

    def test_symlinks(self):
        root = self.repo({'README.md': 'statement extraction'})
        external = self.repo({'a.py': 'x.parse_statement()'})
        (root/'a.py').symlink_to(external/'a.py')
        (root/'linked').symlink_to(external, target_is_directory=True)
        self.assertEqual(audit(root)['findings'][0]['severity'], 'HIGH')

    def test_split_module(self):
        root = self.repo({'README.md': 'statement extraction', 'a.py': 'from veryfi import Client\nc=Client()', 'b.py': 'c.process_bank_statement_document()'})
        self.assertEqual(self.cli(root)[0], 2)

    def test_version_and_module(self):
        result = subprocess.run([sys.executable, '-m', 'bank_statement_extraction_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '0.1.0'))
        root = self.repo({})
        result = subprocess.run([sys.executable, '-m', 'bank_statement_extraction_claim_audit', 'audit', str(root)], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, 'PASS'))

    def test_usage_errors(self):
        for args in ([], ['audit', '--fail-on', 'MEDIUM'], ['audit', '--unknown']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main(args)
            self.assertEqual(raised.exception.code, 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['audit', '/does/not/exist']), 1)

    def test_positive_000(self):
        self.assertTrue(evidence('x.extract_bank_statement()'))

    def test_positive_001(self):
        self.assertTrue(evidence('from library import extract_bank_statement as operation\noperation()'))

    def test_positive_002(self):
        self.assertTrue(evidence('x.extract_bank_statements()'))

    def test_positive_003(self):
        self.assertTrue(evidence('from library import extract_bank_statements as operation\noperation()'))

    def test_positive_004(self):
        self.assertTrue(evidence('x.parse_bank_statement()'))

    def test_positive_005(self):
        self.assertTrue(evidence('from library import parse_bank_statement as operation\noperation()'))

    def test_positive_006(self):
        self.assertTrue(evidence('x.parse_bank_statements()'))

    def test_positive_007(self):
        self.assertTrue(evidence('from library import parse_bank_statements as operation\noperation()'))

    def test_positive_008(self):
        self.assertTrue(evidence('x.extract_statement()'))

    def test_positive_009(self):
        self.assertTrue(evidence('from library import extract_statement as operation\noperation()'))

    def test_positive_010(self):
        self.assertTrue(evidence('x.extract_statements()'))

    def test_positive_011(self):
        self.assertTrue(evidence('from library import extract_statements as operation\noperation()'))

    def test_positive_012(self):
        self.assertTrue(evidence('x.parse_statement()'))

    def test_positive_013(self):
        self.assertTrue(evidence('from library import parse_statement as operation\noperation()'))

    def test_positive_014(self):
        self.assertTrue(evidence('x.parse_statements()'))

    def test_positive_015(self):
        self.assertTrue(evidence('from library import parse_statements as operation\noperation()'))

    def test_positive_016(self):
        self.assertTrue(evidence('x.extract_statement_data()'))

    def test_positive_017(self):
        self.assertTrue(evidence('from library import extract_statement_data as operation\noperation()'))

    def test_positive_018(self):
        self.assertTrue(evidence('x.statement_extraction()'))

    def test_positive_019(self):
        self.assertTrue(evidence('from library import statement_extraction as operation\noperation()'))

    def test_positive_020(self):
        self.assertTrue(evidence('x.statement_extractor()'))

    def test_positive_021(self):
        self.assertTrue(evidence('from library import statement_extractor as operation\noperation()'))

    def test_positive_022(self):
        self.assertTrue(evidence('x.statement_parser()'))

    def test_positive_023(self):
        self.assertTrue(evidence('from library import statement_parser as operation\noperation()'))

    def test_positive_024(self):
        self.assertTrue(evidence('x.bank_statement_extraction()'))

    def test_positive_025(self):
        self.assertTrue(evidence('from library import bank_statement_extraction as operation\noperation()'))

    def test_positive_026(self):
        self.assertTrue(evidence('x.bank_statement_extractor()'))

    def test_positive_027(self):
        self.assertTrue(evidence('from library import bank_statement_extractor as operation\noperation()'))

    def test_positive_028(self):
        self.assertTrue(evidence('x.extract_statement_transactions()'))

    def test_positive_029(self):
        self.assertTrue(evidence('from library import extract_statement_transactions as operation\noperation()'))

    def test_positive_030(self):
        self.assertTrue(evidence('x.parse_statement_transactions()'))

    def test_positive_031(self):
        self.assertTrue(evidence('from library import parse_statement_transactions as operation\noperation()'))

    def test_positive_032(self):
        self.assertTrue(evidence('x.statement_transaction_extraction()'))

    def test_positive_033(self):
        self.assertTrue(evidence('from library import statement_transaction_extraction as operation\noperation()'))

    def test_positive_034(self):
        self.assertTrue(evidence('x.extract_statement_balance()'))

    def test_positive_035(self):
        self.assertTrue(evidence('from library import extract_statement_balance as operation\noperation()'))

    def test_positive_036(self):
        self.assertTrue(evidence('x.extract_transactions_from_statement()'))

    def test_positive_037(self):
        self.assertTrue(evidence('from library import extract_transactions_from_statement as operation\noperation()'))

    def test_positive_038(self):
        self.assertTrue(evidence('x.statement_data_extraction()'))

    def test_positive_039(self):
        self.assertTrue(evidence('from library import statement_data_extraction as operation\noperation()'))

    def test_positive_040(self):
        self.assertTrue(evidence('x.extract_account_statement()'))

    def test_positive_041(self):
        self.assertTrue(evidence('from library import extract_account_statement as operation\noperation()'))

    def test_positive_042(self):
        self.assertTrue(evidence('x.parse_account_statement()'))

    def test_positive_043(self):
        self.assertTrue(evidence('from library import parse_account_statement as operation\noperation()'))

    def test_positive_044(self):
        self.assertTrue(evidence('x.account_statement_extraction()'))

    def test_positive_045(self):
        self.assertTrue(evidence('from library import account_statement_extraction as operation\noperation()'))

    def test_positive_046(self):
        self.assertTrue(evidence('x.account_statement_parser()'))

    def test_positive_047(self):
        self.assertTrue(evidence('from library import account_statement_parser as operation\noperation()'))

    def test_positive_048(self):
        self.assertTrue(evidence('from azure.ai.formrecognizer import DocumentAnalysisClient as C\nc=C()\nx.begin_analyze_document("prebuilt-bankStatement.us")'))

    def test_positive_049(self):
        self.assertTrue(evidence('import azure.ai.documentintelligence as az\nc=az.DocumentIntelligenceClient()\nx.begin_analyze_document_from_url(model_id="prebuilt-bankStatement.us")'))

    def test_positive_050(self):
        self.assertTrue(evidence('import azure.ai.formrecognizer\nc=azure.ai.formrecognizer.DocumentAnalysisClient()\nx.begin_analyze_document(model_id="prebuilt-bankStatement.us")'))

    def test_positive_051(self):
        self.assertTrue(evidence('from veryfi import Client as C\nc=C()\nx.process_bank_statement_document()'))

    def test_positive_052(self):
        self.assertTrue(evidence('import veryfi\nc=veryfi.Client()\nx.process_bank_statement_document_url()'))

    def test_positive_053(self):
        self.assertTrue(evidence('from library import extract_statement as e\nf=e\nf()'))

    def test_positive_054(self):
        self.assertTrue(evidence('from library import extract_statement as e\nf: object=e\nf()'))

    def test_negative_000(self):
        self.assertFalse(evidence('import veryfi'))

    def test_negative_001(self):
        self.assertFalse(evidence('import azure.ai.formrecognizer'))

    def test_negative_002(self):
        self.assertFalse(evidence('import azure.ai.documentintelligence'))

    def test_negative_003(self):
        self.assertFalse(evidence('import mindee'))

    def test_negative_004(self):
        self.assertFalse(evidence('import boto3'))

    def test_negative_005(self):
        self.assertFalse(evidence('from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()'))

    def test_negative_006(self):
        self.assertFalse(evidence("from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()\nx.begin_analyze_document('prebuilt-invoice')"))

    def test_negative_007(self):
        self.assertFalse(evidence("from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()\nx.begin_analyze_document('prebuilt-receipt')"))

    def test_negative_008(self):
        self.assertFalse(evidence("from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()\nx.begin_analyze_document('prebuilt-layout')"))

    def test_negative_009(self):
        self.assertFalse(evidence("from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()\nx.begin_analyze_document('prebuilt-read')"))

    def test_negative_010(self):
        self.assertFalse(evidence("from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()\nx.begin_analyze_document('prebuilt-idDocument')"))

    def test_negative_011(self):
        self.assertFalse(evidence("from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()\nx.begin_analyze_document('prebuilt-check.us')"))

    def test_negative_012(self):
        self.assertFalse(evidence("from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()\nx.begin_analyze_document('prebuilt-payStub.us')"))

    def test_negative_013(self):
        self.assertFalse(evidence("from azure.ai.formrecognizer import DocumentAnalysisClient\nc=DocumentAnalysisClient()\nx.begin_analyze_document('prebuilt-bankStatement')"))

    def test_negative_014(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()'))

    def test_negative_015(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.process_document()'))

    def test_negative_016(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.process_document_url()'))

    def test_negative_017(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.process_check()'))

    def test_negative_018(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.process_check_url()'))

    def test_negative_019(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.process_check_with_remittance()'))

    def test_negative_020(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.process_check_with_remittance_url()'))

    def test_negative_021(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.classify_document()'))

    def test_negative_022(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.get_bank_statement()'))

    def test_negative_023(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.get_bank_statements()'))

    def test_negative_024(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.delete_bank_statement()'))

    def test_negative_025(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.get_check()'))

    def test_negative_026(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.get_checks()'))

    def test_negative_027(self):
        self.assertFalse(evidence('import veryfi\nc=veryfi.Client()\nc.update_check()'))

    def test_negative_028(self):
        self.assertFalse(evidence('import mindee\nc=mindee.Client()\nc.parse(BankCheckV1)'))

    def test_negative_029(self):
        self.assertFalse(evidence('import mindee\nc=mindee.Client()\nc.parse(InvoiceV4)'))

    def test_negative_030(self):
        self.assertFalse(evidence('import mindee\nc=mindee.Client()\nc.parse(ReceiptV5)'))

    def test_negative_031(self):
        self.assertFalse(evidence('import mindee\nc=mindee.Client()\nc.parse(PassportV1)'))

    def test_negative_032(self):
        self.assertFalse(evidence('import mindee\nc=mindee.Client()\nc.parse(FinancialDocumentV1)'))

    def test_negative_033(self):
        self.assertFalse(evidence('import mindee\nc=mindee.Client()\nc.parse(BankAccountDetailsV2)'))

    def test_negative_034(self):
        self.assertFalse(evidence('import mindee\nc=mindee.Client()\nc.parse(CustomV1)'))

    def test_negative_035(self):
        self.assertFalse(evidence('import mindee\nc=mindee.Client()\nc.parse(AnyProduct)'))

    def test_negative_036(self):
        self.assertFalse(evidence('x.analyze_document()'))

    def test_negative_037(self):
        self.assertFalse(evidence('x.analyze_expense()'))

    def test_negative_038(self):
        self.assertFalse(evidence('x.start_document_analysis()'))

    def test_negative_039(self):
        self.assertFalse(evidence('x.get_expense_analysis()'))

    def test_negative_040(self):
        self.assertFalse(evidence('x.extract_text()'))

    def test_negative_041(self):
        self.assertFalse(evidence('x.image_to_string()'))

    def test_negative_042(self):
        self.assertFalse(evidence('x.read_csv()'))

    def test_negative_043(self):
        self.assertFalse(evidence('x.read_excel()'))

    def test_negative_044(self):
        self.assertFalse(evidence('x.read_pdf()'))

    def test_negative_045(self):
        self.assertFalse(evidence('x.convert_into()'))

    def test_negative_046(self):
        self.assertFalse(evidence('x.extract_table()'))

    def test_negative_047(self):
        self.assertFalse(evidence('x.extract_tables()'))

    def test_negative_048(self):
        self.assertFalse(evidence('x.find_table()'))

    def test_negative_049(self):
        self.assertFalse(evidence('x.find_tables()'))

    def test_negative_050(self):
        self.assertFalse(evidence('import re\ntext=ocr()\nfields={"balance":re.search("balance", text)}'))

    def test_negative_051(self):
        self.assertFalse(evidence('transactions = [line.split(",") for line in text.splitlines()]'))

    def test_negative_052(self):
        self.assertFalse(evidence('import subprocess\nsubprocess.run(["veryfi", "bank-statements", "process"])'))

    def test_negative_053(self):
        self.assertFalse(evidence('import subprocess\nsubprocess.run(["mindee", "parse"])'))

    def test_negative_054(self):
        self.assertFalse(evidence('extract_statement()'))

    def test_negative_055(self):
        self.assertFalse(evidence('x.extract_statement'))

    def test_negative_056(self):
        self.assertFalse(evidence('"x.extract_statement()"'))

    def test_negative_057(self):
        self.assertFalse(evidence('# x.extract_statement()'))

    def test_negative_058(self):
        self.assertFalse(evidence('invalid syntax !!!'))

    def test_negative_059(self):
        self.assertFalse(evidence('def extract_statement(): pass\nx.extract_statement()'))

    def test_negative_060(self):
        self.assertFalse(evidence('class extract_statement: pass\nx.extract_statement()'))

    def test_negative_061(self):
        self.assertFalse(evidence('class Wrapper:\n def extract_statement(self): pass\nx.extract_statement()'))

    def test_negative_062(self):
        self.assertFalse(evidence('from library import extract_statement\nwith other() as extract_statement:\n extract_statement()'))

    def test_negative_063(self):
        self.assertFalse(evidence('from library import extract_statement\nextract_statement = other()\nextract_statement()'))

    def test_negative_064(self):
        self.assertFalse(evidence('from library import extract_statement\nextract_statement: object = other()\nextract_statement()'))

    def test_negative_065(self):
        self.assertFalse(evidence('import veryfi\ndef Client(): pass\nx=veryfi.Client()\nx.process_bank_statement_document()'))

EXPECTED_POSITIVE = ('statement extraction', 'extract statements', 'extracts statements', 'extracting statements', 'extract statement', 'extracts statement', 'extracting statement', 'statement parsing', 'statement parser', 'parse statements', 'parses statements', 'parse statement', 'parses statement', 'bank statement extraction', 'extract bank statements', 'extracts bank statements', 'extracting bank statements', 'extract bank statement', 'extracts bank statement', 'extracting bank statement', 'bank statement data extraction', 'extract bank statement data', 'extracts bank statement data', 'extracting bank statement data', 'bank statement parsing', 'bank statement parser', 'parse bank statements', 'parses bank statements', 'parse bank statement', 'parses bank statement', 'us bank statement extraction', 'extract bank statement fields', 'extract bank statement transactions', 'extracts bank statement transactions', 'extracting bank statement transactions', 'parse bank statement transactions', 'statement transaction extraction', 'extract statement transactions', 'extracts statement transactions', 'extracting statement transactions', 'bank statement transaction extraction', 'extract transactions from bank statements', 'extracts transactions from bank statements', 'extracting transactions from bank statements', 'statement balance extraction', 'extract statement balances', 'extract bank statement balance', 'extracts bank statement balance', 'statement field extraction', 'extract bank statement details')
EXPECTED_NEGATIVE = ('no bank statement extraction', 'does not extract bank statements', 'does not extract bank statement', 'does not support bank statement extraction', 'without bank statement extraction', 'no statement extraction', 'does not extract statements', 'does not extract statement', 'does not support statement extraction', 'without statement extraction', 'no statement parser', 'does not parse statements', 'does not parse statement', 'bank statement extraction not supported', 'statement extraction not supported', 'no bank statement parser', 'does not parse bank statements', 'does not parse bank statement', 'no bank statement transaction extraction', 'does not extract bank statement transactions', 'does not extract statement transactions', 'no statement transaction extraction', 'does not extract bank statement fields', 'no bank statement field extraction')
EXPECTED_GENERIC = ('extract_bank_statement', 'extract_bank_statements', 'parse_bank_statement', 'parse_bank_statements', 'extract_statement', 'extract_statements', 'parse_statement', 'parse_statements', 'extract_statement_data', 'statement_extraction', 'statement_extractor', 'statement_parser', 'bank_statement_extraction', 'bank_statement_extractor', 'extract_statement_transactions', 'parse_statement_transactions', 'statement_transaction_extraction', 'extract_statement_balance', 'extract_transactions_from_statement', 'statement_data_extraction', 'extract_account_statement', 'parse_account_statement', 'account_statement_extraction', 'account_statement_parser')
