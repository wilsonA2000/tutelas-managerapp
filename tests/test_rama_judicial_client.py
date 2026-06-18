"""Tests del cliente CPNU (Rama Judicial) — SIN red, con fixtures JSON reales
grabados de la API en vivo (2026-06-18, proceso de SARA EDILIA MOGOLLÓN vs SED).

Validan el parseo/normalización; la red se mockea (un fake Session que devuelve
los fixtures según el path)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from backend.services import rama_judicial_client as rj

FIX = Path(__file__).resolve().parent / "fixtures" / "rama_judicial"


def _load(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


class _FakeResp:
    def __init__(self, payload, status=200, headers=None, content=b""):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise rj.requests.HTTPError(f"HTTP {self.status_code}")


class _FakeSession:
    """Router por path: devuelve el fixture correspondiente. `found` controla si
    la consulta por radicado trae proceso o viene vacía."""
    def __init__(self, found=True):
        self.found = found
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        if "NumeroRadicacion" in url:
            return _FakeResp(_load("consulta_hit") if self.found else _load("consulta_miss"))
        if "/Proceso/Detalle/" in url:
            return _FakeResp(_load("detalle"))
        if "/Proceso/Actuaciones/" in url:
            return _FakeResp(_load("actuaciones"))
        raise AssertionError(f"path no mockeado: {url}")


# ── parseo puro (sin red) ─────────────────────────────────────────────────────

def test_iso_to_ddmmyyyy():
    assert rj._iso_to_ddmmyyyy("2026-03-18T00:00:00") == "18/03/2026"
    assert rj._iso_to_ddmmyyyy(None) is None
    assert rj._iso_to_ddmmyyyy("basura") is None


def test_parse_sujetos():
    dte, ddo = rj._parse_sujetos(
        "Demandante: SARA EDILIA MOGOLLÓN BUSTAMANTE | Demandado: SECRETARÍA DE EDUCACIÓN")
    assert dte == "SARA EDILIA MOGOLLÓN BUSTAMANTE"
    assert ddo == "SECRETARÍA DE EDUCACIÓN"
    # roles alternos (tutela)
    dte2, _ = rj._parse_sujetos("Accionante: JUAN PÉREZ | Accionado: ICFES")
    assert dte2 == "JUAN PÉREZ"
    assert rj._parse_sujetos(None) == (None, None)


# ── orquestación (red mockeada) ───────────────────────────────────────────────

def test_consultar_proceso_hit():
    p = rj.consultar_proceso("68001400902420260005500",
                             session=_FakeSession(found=True), throttle=0)
    assert p.encontrado is True
    assert p.id_proceso == 222027970
    assert p.clase == "Tutelas"
    assert p.departamento == "SANTANDER"
    assert p.fecha_radicacion == "18/03/2026"
    assert p.demandante == "SARA EDILIA MOGOLLÓN BUSTAMANTE"
    assert "EDUCACIÓN" in (p.demandado or "")
    assert p.es_privado is False
    # actuaciones normalizadas + datadas
    assert len(p.actuaciones) >= 3
    tipos = [a.actuacion for a in p.actuaciones]
    assert any("Sentencia de Primera Instancia" in (t or "") for t in tipos)
    assert all(a.fecha is None or "/" in a.fecha for a in p.actuaciones)


def test_consultar_proceso_miss():
    p = rj.consultar_proceso("68001400902420260012500",
                             session=_FakeSession(found=False), throttle=0)
    assert p.encontrado is False
    assert p.error == "no_encontrado"
    assert p.actuaciones == []


def test_consultar_proceso_rad_invalido_no_pega_red():
    # rad inválido → ni siquiera intenta red (session que explota si la usan)
    class _Boom:
        headers = {}
        def get(self, *a, **k):
            raise AssertionError("no debió pegar red con rad inválido")
    p = rj.consultar_proceso("123", session=_Boom(), throttle=0)
    assert p.encontrado is False
    assert "inválido" in (p.error or "")


def test_to_dict_serializable():
    p = rj.consultar_proceso("68001400902420260005500",
                             session=_FakeSession(found=True), throttle=0)
    d = p.to_dict()
    assert isinstance(d["actuaciones"], list)
    json.dumps(d)  # no explota
