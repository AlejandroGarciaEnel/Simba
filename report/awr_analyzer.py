from __future__ import annotations

import re
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


def summarize_awr_report(file_path: str | Path) -> str:
    """Analiza un informe AWR HTML y devuelve un resumen amigable para usuarios no técnicos."""
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

    if not findings:
        findings_line = "Hallazgos principales: el informe no incluye hallazgos ADDM."
    else:
        findings_line = "Hallazgos principales: " + ", ".join(findings[:3]) + "."

    summary_lines = [
        f"Resumen AWR para {db_name}.",
        f"Snapshot: {snapshot} | {instance_count} instancias | {host_count} hosts.",
        f"Tiempo DB: {db_time} min | Tiempo transcurrido: {elapsed} min.",
        f"CPU ocupada media observada: {avg_cpu_busy:.2f}%.",
        findings_line,
        _build_conclusion(findings),
    ]
    return "\n".join(summary_lines)


# (palabras clave del hallazgo ADDM, área afectada, RF para contrastar en vivo)
_FINDING_AREAS: list[tuple[tuple[str, ...], str, str]] = [
    (("sql",), "ejecución de sentencias SQL y PL/SQL", "RF002 y RF010"),
    (("cpu",), "consumo de CPU", "RF001 y RF003"),
    (("lock", "enqueue", "contention", "latch", "mutex"), "bloqueos y contención", "RF005 y RF017"),
    (("i/o", "commit", "log file", "wait", "undersized redo"), "latencia de E/S y esperas", "RF015"),
    (("session", "connect", "login", "logon"), "gestión de sesiones y conexiones", "RF014 y RF020"),
    (("memory", "sga", "pga", "buffer cache", "shared pool"), "memoria", "RF008 y RF008.1"),
]


def _build_conclusion(findings: list[str]) -> str:
    if not findings:
        return (
            "Conclusión: el informe no permite identificar un cuello de botella concreto. "
            "Para revisar el estado en vivo puedes usar RF007, RF008 y RF015."
        )

    areas: list[str] = []
    rfs: list[str] = []
    for finding in findings:
        lowered = finding.lower()
        for keywords, area, rf in _FINDING_AREAS:
            if any(keyword in lowered for keyword in keywords) and area not in areas:
                areas.append(area)
                rfs.append(rf)

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


__all__ = ["summarize_awr_report", "analyze_awr_report"]


if __name__ == "__main__":
    print(summarize_awr_report("docs/awr_example.html"))
