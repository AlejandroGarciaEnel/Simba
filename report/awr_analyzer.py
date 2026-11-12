from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AWR_DIR = PROJECT_ROOT / "awr"
AWR_EXAMPLE = PROJECT_ROOT / "docs" / "awr_example.html"
AWR_EXTENSIONS = {".html", ".htm"}


def resolve_awr_path(file_path: str | Path) -> Path:
    """Devuelve la ruta resuelta solo si es el ejemplo de docs/ o un informe dentro de AWR_DIR."""
    candidate = Path(file_path)
    if candidate.name == str(file_path):
        candidate = AWR_DIR / candidate
    elif not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()

    if resolved == AWR_EXAMPLE.resolve():
        return resolved
    if resolved.parent == AWR_DIR.resolve() and resolved.suffix.lower() in AWR_EXTENSIONS:
        return resolved
    raise ValueError(
        "Ruta de informe AWR no permitida: solo se analizan ficheros .html de la carpeta awr/ "
        "o el ejemplo docs/awr_example.html."
    )


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    text = unescape(value)
    text = re.sub(r"<.*?>", " ", text)
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _read_text(file_path: str | Path) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el informe AWR: {path}")
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_first(pattern: str, text: str, default: str = "N/D") -> str:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        return default
    return _clean_text(match.group(1) if match.lastindex else match.group(0)) or default


def _extract_numbers(pattern: str, text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
        candidate = _clean_text(match.group(1))
        normalized = candidate.replace("%", "").replace(",", "")
        try:
            values.append(float(normalized))
        except ValueError:
            continue
    return values


_SQL_ID_PATTERN = re.compile(r"[a-z0-9]{13}")
_NUMBER_PATTERN = re.compile(r"[0-9][0-9,]*(?:\.\d+)?")
MAX_TOP_SQL = 5


@dataclass(frozen=True)
class AwrSql:
    sql_id: str
    elapsed_s: str
    execs: str
    pct_db_time: str


@dataclass(frozen=True)
class FollowupArea:
    """Área afectada y acciones de seguimiento (nombres de herramientas de la lista blanca)."""

    keywords: tuple[str, ...]
    label: str
    rf: str
    actions: tuple[str, ...]


@dataclass(frozen=True)
class AwrAnalysis:
    db_name: str
    snapshot: str
    instance_count: str
    host_count: str
    db_time: str
    elapsed: str
    avg_cpu_busy: float
    findings: tuple[str, ...]
    top_sql: tuple[AwrSql, ...] = ()

    @property
    def areas(self) -> list[FollowupArea]:
        return _match_areas(self.findings)


# Los hallazgos del informe (no confiable) solo seleccionan áreas; las acciones son fijas.
_FINDING_AREAS: list[FollowupArea] = [
    FollowupArea(("sql",), "ejecución de sentencias SQL y PL/SQL", "RF002 y RF010", ()),
    FollowupArea(("cpu",), "consumo de CPU", "RF001 y RF003", ("get_cpu_usage", "get_top_cpu_sessions")),
    FollowupArea(
        ("lock", "enqueue", "contention", "latch", "mutex"),
        "bloqueos y contención",
        "RF005 y RF017",
        ("get_blocking_sessions", "get_table_lock_detection"),
    ),
    FollowupArea(
        ("i/o", "commit", "log file", "wait", "undersized redo"),
        "latencia de E/S y esperas",
        "RF015",
        ("get_latency_wait_metrics",),
    ),
    FollowupArea(
        ("session", "connect", "login", "logon"),
        "gestión de sesiones y conexiones",
        "RF014 y RF020",
        ("detect_pooling", "get_total_sessions"),
    ),
    FollowupArea(
        ("memory", "sga", "pga", "buffer cache", "shared pool"),
        "memoria",
        "RF008 y RF008.1",
        ("get_metrics", "get_sga_info"),
    ),
]

# Seguimiento cuando el informe no permite asociar los hallazgos a un área concreta
GENERIC_FOLLOWUP = FollowupArea(
    (), "estado general de la base de datos", "RF007, RF008 y RF015",
    ("get_database_summary", "get_metrics", "get_latency_wait_metrics"),
)


def _match_areas(findings: tuple[str, ...] | list[str]) -> list[FollowupArea]:
    areas: list[FollowupArea] = []
    for finding in findings:
        lowered = finding.lower()
        for area in _FINDING_AREAS:
            if any(keyword in lowered for keyword in area.keywords) and area not in areas:
                areas.append(area)
    return areas


def _extract_top_sql(text: str, limit: int = MAX_TOP_SQL) -> tuple[AwrSql, ...]:
    section = re.search(
        r"<h3[^>]*>\s*SQL ordered by Elapsed Time[^<]*</h3>.*?</table>", text, re.IGNORECASE | re.DOTALL
    )
    if not section:
        return ()

    def cell(row: str, header: str) -> str:
        match = re.search(rf'headers="{header}"[^>]*>([^<]*)<', row, re.IGNORECASE)
        value = _clean_text(match.group(1)) if match else ""
        return value if _NUMBER_PATTERN.fullmatch(value) else "N/D"

    result: list[AwrSql] = []
    for row in re.findall(r"<tr>(.*?)</tr>", section.group(0), re.IGNORECASE | re.DOTALL):
        id_match = re.search(r'<td[^>]*scope="row"[^>]*>\s*<a[^>]*>([^<]*)</a>', row, re.IGNORECASE)
        # el SQL ID se usará como parámetro de una consulta: solo se acepta el formato Oracle
        sql_id = _clean_text(id_match.group(1)) if id_match else ""
        if not _SQL_ID_PATTERN.fullmatch(sql_id) or any(item.sql_id == sql_id for item in result):
            continue
        result.append(
            AwrSql(
                sql_id=sql_id,
                elapsed_s=cell(row, r"Total Elapsed\(s\)"),
                execs=cell(row, r"Total Execs"),
                pct_db_time=cell(row, r"PercentageofTotal DBtime"),
            )
        )
        if len(result) >= limit:
            break
    return tuple(result)


def parse_awr_report(file_path: str | Path) -> AwrAnalysis:
    """Extrae del informe AWR HTML los datos estructurados que usan el resumen y el seguimiento."""
    text = _read_text(file_path)
    title_match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    db_name = _clean_text(title_match.group(1)) if title_match else "BD desconocida"
    db_name = re.sub(r".*?DB:\s*([A-Z0-9_]+).*", r"\1", db_name, flags=re.IGNORECASE | re.DOTALL) or db_name
    # el informe puede venir de terceros: solo se admite un identificador Oracle (anti prompt injection)
    if not re.fullmatch(r"[A-Za-z0-9_$#]{1,30}", db_name):
        db_name = "BD desconocida"

    snapshot_match = re.search(
        r'headers="SnapshotIds Begin"[^>]*>\s*(\d+)\s*</td>.{0,2000}?headers="SnapshotIds End"[^>]*>\s*(\d+)\s*</td>',
        text,
        re.IGNORECASE | re.DOTALL,
    )
    snapshot = "N/D"
    if snapshot_match:
        snapshot = f"{snapshot_match.group(1)}-{snapshot_match.group(2)}"

    instance_count = _extract_first(
        r'headers="NumberofInstances InReport"[^>]*>\s*(\d+)\s*</td>',
        text,
        default="N/D",
    )

    host_count = _extract_first(
        r'headers="NumberofHosts InReport"[^>]*>\s*(\d+)\s*</td>',
        text,
        default="N/D",
    )

    db_time = _extract_first(
        r'headers="ReportTotal\(minutes\) DBtime"[^>]*>\s*([0-9,]+(?:\.\d+)?)\s*</td>',
        text,
        default="N/D",
    )
    elapsed = _extract_first(
        r'headers="ReportTotal\(minutes\) Elapsedtime"[^>]*>\s*([0-9,]+(?:\.\d+)?)\s*</td>',
        text,
        default="N/D",
    )

    busy_values = _extract_numbers(r"headers=\"%CPU %Busy\".*?class='(?:awrc|awrnc|awrclb|awrnclb)'>\s*([0-9,\.]+)", text)
    avg_cpu_busy = sum(busy_values) / len(busy_values) if busy_values else 0.0

    findings_table = re.search(
        r"Top ADDM Findings by Average Active Sessions.*?</table>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    findings: list[str] = []
    if findings_table:
        rows = re.findall(r"<tr>(.*?)</tr>", findings_table.group(0), re.IGNORECASE | re.DOTALL)
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.IGNORECASE | re.DOTALL)
            if len(cells) < 2:
                continue
            label = _clean_text(cells[0])[:80]
            if label.lower() in {"finding name", "", "top addm findings by average active sessions"}:
                continue
            if label and label not in findings:
                findings.append(label)

    return AwrAnalysis(
        db_name=db_name,
        snapshot=snapshot,
        instance_count=instance_count,
        host_count=host_count,
        db_time=db_time,
        elapsed=elapsed,
        avg_cpu_busy=avg_cpu_busy,
        findings=tuple(findings),
        top_sql=_extract_top_sql(text),
    )


def render_summary(analysis: AwrAnalysis) -> str:
    findings = list(analysis.findings)
    if not findings:
        findings_line = "Hallazgos principales: el informe no incluye hallazgos ADDM."
    else:
        findings_line = "Hallazgos principales: " + ", ".join(findings[:3]) + "."

    summary_lines = [
        f"Resumen AWR para {analysis.db_name}.",
        f"Snapshot: {analysis.snapshot} | {analysis.instance_count} instancias | {analysis.host_count} hosts.",
        f"Tiempo DB: {analysis.db_time} min | Tiempo transcurrido: {analysis.elapsed} min.",
        f"CPU ocupada media observada: {analysis.avg_cpu_busy:.2f}%.",
        findings_line,
    ]
    if analysis.top_sql:
        top = ", ".join(f"{item.sql_id} ({item.elapsed_s} s)" for item in analysis.top_sql)
        summary_lines.append(f"SQL con mayor tiempo en el informe: {top}.")
    summary_lines.append(_build_conclusion(findings))
    return "\n".join(summary_lines)


def summarize_awr_report(file_path: str | Path) -> str:
    """Analiza un informe AWR HTML y devuelve un resumen amigable para usuarios no técnicos."""
    return render_summary(parse_awr_report(file_path))


def _build_conclusion(findings: list[str]) -> str:
    if not findings:
        return (
            "Conclusión: el informe no permite identificar un cuello de botella concreto. "
            "Para revisar el estado en vivo puedes usar RF007, RF008 y RF015."
        )

    matched = _match_areas(findings)
    areas = [area.label for area in matched]
    rfs = [area.rf for area in matched]

    if not areas:
        return (
            f"Conclusión: el hallazgo de mayor impacto es \"{findings[0]}\". "
            "Revisa su detalle en el propio informe AWR; para contrastar en vivo puedes usar RF008 y RF015."
        )
    return (
        f"Conclusión: el hallazgo de mayor impacto es \"{findings[0]}\" y los hallazgos apuntan a: "
        + ", ".join(areas)
        + ". Para confirmar el origen en vivo, contrasta con "
        + ", ".join(rfs)
        + "."
    )


def analyze_awr_report(file_path: str | Path) -> str:
    """Alias de alto nivel para el analizador AWR."""
    return summarize_awr_report(file_path)


__all__ = [
    "AwrAnalysis",
    "AwrSql",
    "FollowupArea",
    "GENERIC_FOLLOWUP",
    "analyze_awr_report",
    "parse_awr_report",
    "render_summary",
    "resolve_awr_path",
    "summarize_awr_report",
]


if __name__ == "__main__":
    print(summarize_awr_report("docs/awr_example.html"))
