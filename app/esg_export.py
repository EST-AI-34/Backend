"""ESG 보고서 내보내기(export) 산출물 생성.

exports 라우트는 esg_reports.status를 EXPORTED로 바꾸기만 하고 실제 파일 바이트를
만들지 않았다(job도 처리 없이 바로 COMPLETED로 기록). 이 모듈은 승인된 보고서의
snapshot(jobs.py의 GENERATE_ESG_REPORT 단계가 채운다)을 실제 PDF/DOCX 바이트로
렌더링해서 jobs.result에 base64로 담아 돌려준다.

파일 저장소 제공자가 아직 정해지지 않아서(README 참고) 외부 업로드 없이 바이트를
job 결과에 직접 넣는다 — esg_evidence의 fileId 연동과 같은 전제.

PDF는 외부 폰트 임베딩 라이브러리 없이 표준 14폰트(Helvetica, Latin-1)로만 그린다.
Latin-1에 없는 한글 문자는 PDF 뷰어에서 제대로 그려지지 않을 수 있어, 한글이 실제로
읽혀야 하면 DOCX를 권장한다(코드 주석 및 운영 문서에 명시). DOCX는 텍스트가 그대로
UTF-8 XML이라 한글이 항상 정확히 표시된다.
"""
import base64
import csv
import json
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile
from io import BytesIO, StringIO


def _format_period(report: dict) -> str:
    period_from = report.get("period_from")
    period_to = report.get("period_to")
    return f"{period_from} ~ {period_to}" if period_from and period_to else ""


def _report_lines(report: dict) -> list[str]:
    """보고서 본문.

    edit_metadata는 저장만 되고 어디에서도 읽히지 않아, 운영자가 편집한 제목·머리말·맺음말이
    산출물에 전혀 반영되지 않았다(format이 EDITABLE_DOCUMENT여도 편집이 무의미했다).
    스냅샷의 수치는 승인 실적이 근거이므로 편집 대상이 아니고, 서술 부분만 덮어쓴다.
    """
    snapshot = report.get("snapshot") or {}
    metrics = snapshot.get("metrics") or []
    edits = report.get("edit_metadata") or {}
    comparison = snapshot.get("comparison") or {}
    lines = [
        str(edits.get("title") or report["title"]),
        f"기간: {_format_period(report)}",
        f"생성 시각: {snapshot.get('generatedAt', '-')}",
    ]
    if edits.get("intro"):
        lines += ["", str(edits["intro"])]
    lines += ["", "지표"]
    if not metrics:
        lines.append("- 승인된 실적이 없습니다.")
    for metric in metrics:
        value = metric.get("value")
        unit = metric.get("unit") or ""
        target = metric.get("target")
        line = (
            f"- {metric.get('name')} ({metric.get('category')}): {value}{unit}"
            f" / 목표 {target}{unit} / 측정 {metric.get('measurementCount', 0)}건"
            f" / 증빙 {metric.get('evidenceCount', 0)}건"
        )
        if metric.get("comparisonValue") is not None:
            delta = metric.get("comparisonDelta")
            line += f" / 비교 축제 {metric['comparisonValue']}{unit} (차이 {delta:+}{unit})"
        lines.append(line)
    if comparison.get("metrics"):
        lines += ["", f"비교 축제: {comparison.get('festivalId', '-')} 같은 기간 승인 실적 {len(comparison['metrics'])}건"]
    if edits.get("note"):
        lines += ["", "비고", str(edits["note"])]
    return lines


def _minimal_pdf(lines: list[str]) -> bytes:
    """표준 14폰트(Helvetica)만 쓰는 최소 단일 페이지 PDF. Latin-1 밖 문자는 그려지지 않을 수 있다."""

    def escape_pdf_text(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    y = 760
    stream_parts = ["BT", "/F1 11 Tf", "12 TL"]
    for index, line in enumerate(lines):
        safe = escape_pdf_text(line.encode("latin-1", errors="replace").decode("latin-1"))[:110]
        if index == 0:
            stream_parts.append(f"72 {y} Td ({safe}) Tj")
        else:
            stream_parts.append(f"T* ({safe}) Tj")
    stream_parts.append("ET")
    stream = "\n".join(stream_parts)
    stream_bytes = stream.encode("latin-1", errors="replace")

    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        None,  # placeholder for the stream object, built below
    ]
    body = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        if obj is None:
            body += f"{index} 0 obj << /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1")
            body += stream_bytes
            body += b"\nendstream\nendobj\n"
        else:
            body += f"{index} 0 obj {obj} endobj\n".encode("latin-1")
    xref_offset = len(body)
    xref = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    xref += "".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:])
    trailer = f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    return body + xref.encode("latin-1") + trailer.encode("latin-1")


_DOCX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_DOCX_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    "</Relationships>"
)


def _minimal_docx(lines: list[str]) -> bytes:
    """python-docx 없이 만드는 최소 유효 DOCX(OOXML). 텍스트가 UTF-8 XML이라 한글이 항상 정확히 보인다."""
    paragraphs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>' for line in lines
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        archive.writestr("_rels/.rels", _DOCX_RELS)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _artifact(content: bytes, file_name: str, mime_type: str) -> dict[str, Any]:
    return {
        "fileName": file_name,
        "mimeType": mime_type,
        "contentBase64": base64.b64encode(content).decode("ascii"),
        "byteSize": len(content),
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def build_table_artifact(rows: list[dict], columns: tuple[str, ...], export_format: str, stem: str) -> dict[str, Any]:
    """운영 데이터 목록을 실제 CSV/JSON 바이트로 만든다.

    CSV는 Excel이 UTF-8로 열도록 BOM을 붙인다 — 없으면 한글 컬럼이 깨져서 보인다.
    """
    if export_format == "JSON":
        content = json.dumps(rows, ensure_ascii=False, default=str, indent=2).encode("utf-8")
        return _artifact(content, f"{stem}.json", "application/json; charset=utf-8")
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: "" if row.get(column) is None else str(row.get(column)) for column in columns})
    return _artifact(b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8"), f"{stem}.csv", "text/csv; charset=utf-8")


def build_report_artifact(report: dict, export_format: str) -> dict[str, Any]:
    """승인된 ESG 보고서 스냅샷으로 실제 파일 바이트를 만들어 base64로 반환한다.

    PDF는 표준 14폰트(Latin-1)만 써서 한글이 '?'로 깨진다. 조용히 깨진 파일을 주는 대신
    `textLossWarning`으로 알려 주고, 운영자 화면이 DOCX를 권할 수 있게 한다.
    """
    lines = _report_lines(report)
    if export_format == "DOCX":
        artifact = _artifact(_minimal_docx(lines), f"esg-report-{report['id']}.docx",
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        return {**artifact, "textLossWarning": None}
    dropped = sum(1 for line in lines for char in line if char.encode("latin-1", errors="replace") == b"?" and char != "?")
    artifact = _artifact(_minimal_pdf(lines), f"esg-report-{report['id']}.pdf", "application/pdf")
    return {**artifact, "textLossWarning": (
        f"PDF는 라틴 문자 전용 표준 폰트만 사용해 한글 {dropped}자가 '?'로 표시됩니다. "
        "한글이 그대로 필요하면 DOCX로 내보내 주세요." if dropped else None)}
