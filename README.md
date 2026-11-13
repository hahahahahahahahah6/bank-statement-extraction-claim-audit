# Documentation claim auditor

An offline audit tool comparing documentation promises with listed call patterns in Python source. Inspected code is parsed, never executed or imported. The auditor has no runtime dependencies, makes no network calls, collects no telemetry, and writes no output files.

## Install and run

Requires Python 3.9 or newer.

```sh
python3 -m pip install .
bank-statement-extraction-claim-audit --version
bank-statement-extraction-claim-audit audit /path/to/repo --json
python3 -m bank_statement_extraction_claim_audit audit . --verbose
bank-statement-extraction-claim-audit audit . --ignore tests --ignore vendor --fail-on medium
python3 -m unittest discover
```

The repository defaults to the current directory. Each repeatable ignore option takes one relative path prefix, matching whole path components. The threshold accepts lowercase high (default) or medium. Exit codes are 0 below the threshold, 2 for findings at or above it, and 1 for usage or I/O errors. A FAIL verdict can exit 0 when findings fall below the threshold. Version output is 0.1.0.

JSON includes verdict, findings, production_evidence and test_evidence. Each finding includes id, severity, message and docs. A positive promise without production evidence receives HIGH, or MEDIUM if evidence exists only in tests. A denial contradicted by production evidence receives HIGH. With no source files a positive promise fails and a denial passes. Each family produces at most one finding.

```text
documented-bank-statement-extraction-claim-false
documented-no-bank-statement-extraction-claim-false
```

## Scope

Documentation means root README.md and Markdown files under any docs path component. Fenced blocks using backticks or tildes with up to three leading spaces are excluded; inline code counts. Paragraphs split on blank lines. Matching lowercases text, expands contractions, replaces hyphens with spaces and collapses whitespace. Exact phrases match at word boundaries, longest first with alphabetical ties. Denial spans are removed before positive matching. The phrase module contains the fixed vocabulary.

Source is parsed with the standard syntax tree parser. Symlinked files and directories are skipped. Source under fixtures, docs and examples supplies no evidence. Files under tests or named with the conventional test prefix or suffix count separately. Invalid syntax supplies no evidence. Paired routes must occur in one module. Imports and simple aliases are resolved; assignments, annotated assignments and context manager bindings are tracked. Local functions, methods and classes shadow matching route names.

```text
Azure: DocumentAnalysisClient / DocumentIntelligenceClient construction
 import azure.ai.formrecognizer / azure.ai.documentintelligence
 begin_analyze_document / begin_analyze_document_from_url
 exact literal model id: prebuilt-bankStatement.us
Veryfi: Client construction + process_bank_statement_document /
 process_bank_statement_document_url
Generic names: 24 exact names in phrases.py
```

## Limits

Static pattern matching is not semantic judgement. Dead code counts; untraceable alias chains are missed. Only listed phrases match; denial handling depends on its finite list. Each paired route must occur in one module. Azure Document Intelligence and Veryfi are cloud APIs: source calls establish neither configured credentials nor successful execution.

Broad wording can refer to code, SQL or witness statements, fixture lists, or transaction rows in an already extracted text dump. These meanings can cause false positives. The tool flags the wording and uses listed code patterns to decide.

```text
statement extraction / extract statement / extract statements
statement parser / statement parsing / parse statement / parse statements
extract statement transactions / statement transaction extraction
```

Generic calls may implement SQL or code parsing, wrap an external binary, or parse numbers typed by a user. Listed calls count subject to shadowing. A thin wrapper containing only subprocess calls supplies no evidence. Parsing already extracted transaction strings alone and handwritten regular expressions over OCR text with manual field assembly are missed unless a listed call occurs.

```text
extract_statement / parse_statement
extract_statement_balance / extract_transactions_from_statement
re.search / re.findall
subprocess: veryfi bank-statements process; mindee CLI; any other external CLI
```

Generic document operations below are excluded. Veryfi generic processing handles receipts and invoices; checks are a separate document type. Retrieval and management of already processed documents do not establish the checked operation. Azure requires the exact regional suffix; the bare spelling is not a real v4.0 model id. Other models cover other document types. Mindee has no product for the checked document type in its Python SDK, verified against wheel 4.22.0 on 2026-11-13. Its French account details product covers RIB details. Every Mindee product is excluded. Textract has no operation for the checked document type; generic document and expense analysis do not count.

```text
Veryfi excluded: process_document / process_document_url
 process_check / process_check_url / process_check_with_remittance /
 process_check_with_remittance_url / classify_document
 get_bank_statements / get_bank_statement / delete_bank_statement
 get_check / get_checks / update_check
Azure excluded model ids: prebuilt-bankStatement (missing .us)
 prebuilt-invoice / prebuilt-receipt / prebuilt-layout / prebuilt-read /
 prebuilt-idDocument / prebuilt-check.us / prebuilt-payStub.us
Mindee parse: ANY product, including BankCheckV1, InvoiceV4, ReceiptV5,
 PassportV1, FinancialDocumentV1, BankAccountDetailsV2, CustomV1
Textract: analyze_document / analyze_expense /
 start_document_analysis / get_expense_analysis
```

Plain text, OCR, spreadsheet loading and table operations alone do not count. Bare imports, strings, comments, bare references, invalid syntax and paired evidence split between modules do not count. Adjacent document types and authenticity or fraud promises below are outside the phrase lists: verification differs from retrieving fields.

```text
pdfplumber / fitz / pypdf / PyPDF2 / pdfminer: extract_text
pytesseract: image_to_string; pandas: read_csv / read_excel
camelot: read_pdf; tabula: read_pdf / convert_into
pdfplumber: extract_table / extract_tables / find_table / find_tables
fitz: find_tables
invoice extraction / extract invoices
receipt extraction / extract receipts
ID document extraction / extract passports / passport extraction
bank check extraction / extract bank checks / check extraction
verify statement / fake statement detection / statement fraud detection
```

MIT licensed.
