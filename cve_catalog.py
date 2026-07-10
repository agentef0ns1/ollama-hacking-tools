"""
Catalogo de CVEs conocidos en Ollama y motor de correlacion por version.

Referencias: Ollama_security.md (TFM) + advisories publicos.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal["RCE", "DoS", "Disclosure", "Auth", "Network"]


@dataclass(frozen=True)
class CVERecord:
    id: str
    alias: str
    severity: Severity
    cvss: str | None
    category: Category
    endpoint: str
    affected_range: str
    fixed_in: str | None
    max_vulnerable: str | None
    platform: str | None
    description: str
    mechanism: str
    impact: str
    uncertain: bool = False


OLLAMA_CVES: tuple[CVERecord, ...] = (
    CVERecord(
        id="CVE-2024-37032",
        alias="Probllama",
        severity="critical",
        cvss="9.8",
        category="RCE",
        endpoint="POST /api/pull",
        affected_range="< 0.1.34",
        fixed_in="0.1.34",
        max_vulnerable=None,
        platform=None,
        description="Path Traversal (CWE-22) en el endpoint POST /api/pull.",
        mechanism="Manifiesto con blobs y secuencias ../../ en digests; escritura fuera del directorio Ollama.",
        impact="Sobrescritura de archivos del SO / RCE y control total del servidor.",
    ),
    CVERecord(
        id="CVE-2024-39721",
        alias="Goroutine Blocking DoS",
        severity="high",
        cvss=None,
        category="DoS",
        endpoint="POST /api/create",
        affected_range="< 0.1.34",
        fixed_in="0.1.34",
        max_vulnerable=None,
        platform=None,
        description="DoS por bloqueo de goroutines en CreateModelHandler.",
        mechanism="Campo path apuntando a /dev/random o /dev/zero; lectura bloqueante infinita.",
        impact="Agotamiento de goroutines y caida del servicio de inferencia.",
    ),
    CVERecord(
        id="CVE-2024-28224",
        alias="DNS Rebinding",
        severity="high",
        cvss=None,
        category="Network",
        endpoint="* (localhost bypass)",
        affected_range="< 0.1.29",
        fixed_in="0.1.29",
        max_vulnerable=None,
        platform=None,
        description="Ataque DNS Rebinding contra API local.",
        mechanism="Engano del navegador victima para llamar localhost:11434 desde origen malicioso.",
        impact="Exfiltracion y borrado remoto de modelos sin exposicion directa a Internet.",
    ),
    CVERecord(
        id="CVE-2025-0315",
        alias="DoS RAM exhaustion",
        severity="high",
        cvss=None,
        category="DoS",
        endpoint="POST /api/create",
        affected_range="<= 0.3.14",
        fixed_in="0.3.15",
        max_vulnerable="0.3.14",
        platform=None,
        description="Asignacion ilimitada de RAM con modelos GGUF corruptos.",
        mechanism="Modelo GGUF alterado provoca reserva de memoria sin limite.",
        impact="Colapso del sistema por agotamiento de RAM.",
    ),
    CVERecord(
        id="CVE-2025-0317",
        alias="ggufPadding div-by-zero",
        severity="high",
        cvss=None,
        category="DoS",
        endpoint="POST /api/create",
        affected_range="<= 0.3.14",
        fixed_in="0.3.15",
        max_vulnerable="0.3.14",
        platform=None,
        description="Division por cero en ggufPadding al procesar modelos custom.",
        mechanism="GGUF malformado dispara fallo aritmetico en el parser.",
        impact="Caida inmediata del proceso servidor.",
    ),
    CVERecord(
        id="CVE-2025-0312",
        alias="Null pointer DoS",
        severity="high",
        cvss=None,
        category="DoS",
        endpoint="POST /api/create",
        affected_range="<= 0.3.14",
        fixed_in="0.3.15",
        max_vulnerable="0.3.14",
        platform=None,
        description="Desreferencia de puntero nulo con modelos personalizados.",
        mechanism="Modelo corrupto provoca crash en parseo GGUF.",
        impact="Denegacion de servicio instantanea.",
    ),
    CVERecord(
        id="CVE-2025-63389",
        alias="Authentication Bypass",
        severity="critical",
        cvss=None,
        category="Auth",
        endpoint="API endpoints (proxy bypass)",
        affected_range="desconocido",
        fixed_in=None,
        max_vulnerable=None,
        platform=None,
        description="Bypass de autenticacion en endpoints de la plataforma Ollama.",
        mechanism="Evasion de controles perimetrales si el proxy no esta endurecido.",
        impact="Acceso no autorizado a APIs protegidas superficialmente.",
        uncertain=True,
    ),
    CVERecord(
        id="CVE-2026-42248",
        alias="Windows unsigned updates",
        severity="critical",
        cvss=None,
        category="RCE",
        endpoint="Auto-update (cliente Windows)",
        affected_range="cliente Windows (verificar)",
        fixed_in=None,
        max_vulnerable=None,
        platform="windows",
        description="Actualizacion automatica sin verificacion de firma digital.",
        mechanism="MitM / envenenamiento DNS inyecta binarios en descargas silenciosas.",
        impact="Ejecucion de codigo malicioso con persistencia en Startup.",
        uncertain=True,
    ),
    CVERecord(
        id="CVE-2026-42249",
        alias="Windows update path traversal",
        severity="critical",
        cvss=None,
        category="RCE",
        endpoint="Auto-update (cliente Windows)",
        affected_range="cliente Windows (verificar)",
        fixed_in=None,
        max_vulnerable=None,
        platform="windows",
        description="Path Traversal en actualizador Windows via cabeceras HTTP controladas.",
        mechanism="Rutas de instalacion manipuladas hacia carpetas de inicio automatico.",
        impact="Persistencia y RCE sin interaccion del usuario.",
        uncertain=True,
    ),
    CVERecord(
        id="CVE-2026-7482",
        alias="Bleeding Llama",
        severity="critical",
        cvss=None,
        category="Disclosure",
        endpoint="POST /api/create",
        affected_range="sin auth (verificar parche)",
        fixed_in=None,
        max_vulnerable=None,
        platform=None,
        description="Memory disclosure en parseo GGUF (Bleeding Llama).",
        mechanism="Tensores manipulados en GGUF malicioso; lectura fuera de buffers asignados.",
        impact="Extraccion de chats, prompts, tokens API y datos en RAM del host.",
        uncertain=True,
    ),
)


def parse_version(version_str: str) -> tuple[int, ...]:
    cleaned = version_str.strip().lstrip("vV")
    match = re.match(r"(\d+(?:\.\d+)*)", cleaned)
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def _pad(parts: tuple[int, ...], length: int) -> tuple[int, ...]:
    return parts + (0,) * (length - len(parts))


def compare_versions(a: str, b: str) -> int:
    pa, pb = parse_version(a), parse_version(b)
    length = max(len(pa), len(pb))
    pa, pb = _pad(pa, length), _pad(pb, length)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def is_vulnerable(detected: str, cve: CVERecord, *, platform: str | None = None) -> bool | None:
    """
    True  = probablemente vulnerable
    False = parcheado segun version conocida
    None  = requiere verificacion manual
    """
    if cve.uncertain or (cve.fixed_in is None and cve.max_vulnerable is None):
        if cve.platform and platform and cve.platform.lower() not in platform.lower():
            return False
        return None

    if cve.platform and platform and cve.platform.lower() not in platform.lower():
        return False

    if cve.fixed_in and compare_versions(detected, cve.fixed_in) < 0:
        return True
    if cve.max_vulnerable and compare_versions(detected, cve.max_vulnerable) <= 0:
        return True
    return False


def _risk_level(vulnerable: list, uncertain: list) -> str:
    if any(c.severity == "critical" for c in vulnerable):
        return "CRITICAL"
    if vulnerable:
        return "HIGH"
    if uncertain:
        return "MEDIUM"
    return "LOW"


def scan_version(
    version: str | None,
    *,
    platform: str | None = None,
    version_detected: bool = True,
) -> dict[str, Any]:
    if not version or not version_detected:
        return {
            "version": version or "desconocida",
            "version_detected": False,
            "risk_level": "UNKNOWN",
            "summary": {
                "total_cves": len(OLLAMA_CVES),
                "vulnerable": 0,
                "patched": 0,
                "manual_check": len(OLLAMA_CVES),
            },
            "vulnerable": [],
            "patched": [],
            "manual_check": [asdict(c) for c in OLLAMA_CVES],
            "message": "No se pudo obtener version via GET /api/version. Ejecutar scan manual.",
        }

    vulnerable: list[dict[str, Any]] = []
    patched: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []

    for cve in OLLAMA_CVES:
        record = asdict(cve)
        status = is_vulnerable(version, cve, platform=platform)
        record["status"] = (
            "VULNERABLE" if status is True else "PATCHED" if status is False else "MANUAL_CHECK"
        )
        if status is True:
            vulnerable.append(record)
        elif status is False:
            patched.append(record)
        else:
            manual.append(record)

    risk = _risk_level(
        [c for c in OLLAMA_CVES if is_vulnerable(version, c, platform=platform) is True],
        [c for c in OLLAMA_CVES if is_vulnerable(version, c, platform=platform) is None],
    )

    exploitable_endpoints = sorted({c["endpoint"] for c in vulnerable + manual})

    return {
        "version": version,
        "version_detected": True,
        "platform_hint": platform,
        "risk_level": risk,
        "summary": {
            "total_cves": len(OLLAMA_CVES),
            "vulnerable": len(vulnerable),
            "patched": len(patched),
            "manual_check": len(manual),
        },
        "exploitable_endpoints": exploitable_endpoints,
        "vulnerable": vulnerable,
        "patched": patched,
        "manual_check": manual,
        "message": (
            f"Version {version}: {len(vulnerable)} CVE(s) probables, "
            f"{len(patched)} parcheados, {len(manual)} requieren verificacion."
        ),
    }
