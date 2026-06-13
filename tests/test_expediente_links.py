"""Tests de la capa de links de expediente (OneDrive del juzgado).

Caso real que motivó el módulo (e2038/c575/c395, 2026-06-12): el subject traía
el rad con typo (2022-00027) y creó un cascarón; el link de OneDrive contenía
el rad verdadero en el path (.../69432318900120220012700/003SegundoIncidente
Desacato) — con OTRO typo del juzgado en el prefijo DANE (69432 por 68432).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base
from backend.email.expediente_links import (
    harvest_expediente_links,
    parse_expediente_link,
    parse_server_path,
    rad23_suffix_key,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()

# El link tokenizado REAL del correo e2038 (carpeta compartida por el juzgado)
TOKENIZED = ("https://etbcsj-my.sharepoint.com/:f:/g/personal/"
             "j01prctomalaga_cendoj_ramajudicial_gov_co/"
             "IgAG_XgnbCZvSYJXW4-2y6xEARdCIkgE5ROvOsZ2_3vzUNM?e=aYwfUp")

# La vista web a la que redirige (con el path en id=, URL-encoded)
ONEDRIVE_VIEW = ("https://etbcsj-my.sharepoint.com/personal/"
                 "j01prctomalaga_cendoj_ramajudicial_gov_co/_layouts/15/onedrive.aspx"
                 "?id=%2Fpersonal%2Fj01prctomalaga%5Fcendoj%5Framajudicial%5Fgov%5Fco"
                 "%2FDocuments%2F006AccionesTutelaPrimeraInstancia%2FARCHIVADO"
                 "%2F02Tutelas2022%2F69432318900120220012700%2F003SegundoIncidenteDesacato"
                 "&ga=1")


class TestHarvest:
    def test_harvest_tokenized(self):
        text = f"Cordial saludo,\nse comparte expediente: {TOKENIZED} \nAtentamente"
        assert harvest_expediente_links(text) == [TOKENIZED]

    def test_harvest_onedrive_view(self):
        links = harvest_expediente_links(f"ver: {ONEDRIVE_VIEW}")
        assert links == [ONEDRIVE_VIEW]

    def test_harvest_dedup_y_orden(self):
        text = f"{TOKENIZED}\notra vez {TOKENIZED}\ny la vista {ONEDRIVE_VIEW}"
        assert harvest_expediente_links(text) == [TOKENIZED, ONEDRIVE_VIEW]

    def test_harvest_vacio(self):
        assert harvest_expediente_links("") == []
        assert harvest_expediente_links(None) == []
        assert harvest_expediente_links("sin links http://otro.com/x") == []


class TestParse:
    def test_tokenized_no_trae_path(self):
        info = parse_expediente_link(TOKENIZED)
        assert info.kind == "share_folder"
        assert info.owner == "j01prctomalaga_cendoj_ramajudicial_gov_co"
        assert info.juzgado_hint == "j01prctomalaga"
        assert info.server_path == ""   # requiere red para resolver
        assert info.rad23_url == ""

    def test_onedrive_view_trae_todo(self):
        info = parse_expediente_link(ONEDRIVE_VIEW)
        assert info.kind == "onedrive_view"
        assert info.owner == "j01prctomalaga_cendoj_ramajudicial_gov_co"
        assert info.rad23_url == "69432318900120220012700"
        assert info.etapa == "003SegundoIncidenteDesacato"
        assert info.instancia_hint == "006AccionesTutelaPrimeraInstancia"
        assert info.archivado is True

    def test_parse_server_path_carpeta_raiz_del_rad(self):
        # cuando comparten la RAÍZ del expediente, etapa queda vacía
        d = parse_server_path("/personal/x/Documents/02Tutelas2022/68432318900120220012700")
        assert d["rad23_url"] == "68432318900120220012700"
        assert d["etapa"] == ""

    def test_parse_server_path_rad_embebido(self):
        # caso real: el juzgado nombra la carpeta con texto alrededor del rad
        d = parse_server_path("/personal/x/Documents/Tutelas/03) 684644089001202500107Educación")
        assert d["rad23_url"] == "684644089001202500107"
        assert d["etapa"] == ""  # la carpeta del caso, no una etapa

    def test_parse_server_path_rad_embebido_con_etapa(self):
        d = parse_server_path("/personal/x/Documents/03) 684644089001202500107Educación/002SegundaInstancia")
        assert d["rad23_url"] == "684644089001202500107"
        assert d["etapa"] == "002SegundaInstancia"

    def test_share_file(self):
        info = parse_expediente_link(TOKENIZED.replace("/:f:/", "/:b:/"))
        assert info.kind == "share_file"


class TestSuffixKey:
    def test_typo_dane_mismo_sufijo(self):
        # typo real del juzgado: 69432... por 68432... — el sufijo [5:21] coincide
        assert rad23_suffix_key("69432318900120220012700") == rad23_suffix_key("68432318900120220012700")
        assert rad23_suffix_key("68432318900120220012700") == "3189001202200127"

    def test_distinto_consecutivo_distinto_sufijo(self):
        assert rad23_suffix_key("68432318900120220012700") != rad23_suffix_key("68432318900120220002700")

    def test_corto_devuelve_vacio(self):
        assert rad23_suffix_key("2022-00127") == ""
        assert rad23_suffix_key(None) == ""


class TestMatcherSignal:
    """La señal rad23_url debe auto-matchear el caso (≥70) — el anti-cascarón."""

    def _cache(self):
        from backend.email.case_lookup_cache import CaseLookupCache
        cache = CaseLookupCache()
        # c395 indexado como lo hace build(): key = norm[:21]
        cache.by_rad23["684323189001202200127"] = 395
        cache.juzgado12[395] = "684323189001"
        cache._built = True
        return cache

    def test_lookup_suffix_typo_dane(self):
        cache = self._cache()
        assert cache.lookup_by_rad23_suffix("69432318900120220012700") == 395

    def test_lookup_suffix_ambiguo_none(self):
        cache = self._cache()
        cache.by_rad23["694323189001202200127"] = 999  # mismo sufijo, otro caso
        assert cache.lookup_by_rad23_suffix("69432318900120220012700") is None

    def test_score_rad23_url_evita_cascaron(self):
        """Escenario e2038 completo: subject con rad typo (no matchea nada),
        link con rad verdadero (typo DANE) → auto-match HIGH a c395."""
        from backend.email.matcher import EmailSignals, score_case_match
        cache = self._cache()
        signals = EmailSignals(
            rad23="68432318900120220002700",   # del subject (typo 00027)
            rad_corto="2022-00027",
            rad23_url="69432318900120220012700",  # del link (typo DANE, rad real)
            sender="juzgado@cendoj.ramajudicial.gov.co",
        )
        match = score_case_match(None, cache, signals)
        assert match.case_id == 395
        assert match.score >= 70
        assert match.confidence == "HIGH"
        assert "rad23_url_suffix" in match.breakdown.get("signals", {}) or \
               "rad23_url_suffix" in str(match.breakdown)

    def test_score_rad23_url_exacto(self):
        from backend.email.matcher import EmailSignals, score_case_match
        cache = self._cache()
        signals = EmailSignals(rad23_url="68432318900120220012700")
        match = score_case_match(None, cache, signals)
        assert match.case_id == 395
        assert match.score >= 70

    def test_has_any_incluye_rad23_url(self):
        from backend.email.matcher import EmailSignals
        assert EmailSignals(rad23_url="68432318900120220012700").has_any()
        assert not EmailSignals().has_any()


class TestFetcherPuro:
    """Partes del fetcher sin red."""

    def test_safe_filename(self):
        from backend.services.expediente_fetcher import _safe_filename
        assert _safe_filename("003SegundoIncidenteDesacato", "042Notificacion.pdf") == \
            "EXPJ_003SegundoIncidenteDesacato_042Notificacion.pdf"
        assert _safe_filename("", "a:b.pdf") == "EXPJ_a_b.pdf"

    def test_api_base(self):
        from backend.services.expediente_fetcher import _api_base
        assert _api_base(
            "etbcsj-my.sharepoint.com",
            "/personal/j01prctomalaga_cendoj_ramajudicial_gov_co/Documents/x",
        ) == "https://etbcsj-my.sharepoint.com/personal/j01prctomalaga_cendoj_ramajudicial_gov_co"

    def test_es_link_judicial(self):
        from backend.email.expediente_links import es_link_judicial
        assert es_link_judicial(TOKENIZED)  # etbcsj
        assert not es_link_judicial(
            "https://santandergov-my.sharepoint.com/:w:/g/personal/apoyojuridicosed_santander_gov_co/Iabc")


class TestConflictGuard:
    """El guard que impide contaminar una carpeta con OTRO expediente (post-c575)."""

    class _FakeLink:
        def __init__(self, case_id, rad23_url):
            self.id = 1
            self.case_id = case_id
            self.url = "https://etbcsj-my.sharepoint.com/:f:/g/personal/x/Iabc?e=z"
            self.rad23_url = rad23_url
            self.estado = "RESUELTO"
            self.error_detail = ""
            self.server_path = ""
            self.etapa = ""
            self.instancia_hint = ""
            self.archivado = False
            self.owner = ""
            self.n_files = 0
            self.n_descargados = 0
            self.last_checked = None

    def _patch_resolve(self, monkeypatch, server_path, rad_url):
        import backend.services.expediente_fetcher as fx
        monkeypatch.setattr(fx, "resolve_share_link", lambda url, **kw: {
            "estado": "RESUELTO", "session": None, "host": "etbcsj-my.sharepoint.com",
            "owner": "x", "server_path": server_path, "rad23_url": rad_url,
            "etapa": "", "instancia_hint": "", "archivado": False,
        })
        monkeypatch.setattr(fx, "list_folder", lambda *a, **k: [
            {"name": "001.pdf", "size": 1000, "modified": "", "server_path": server_path + "/001.pdf", "subfolder": ""}])

    def test_conflicto_no_descarga(self, monkeypatch, db_session, tmp_path):
        """rad del link ≠ rad del caso → CONFLICTO, sin tocar disco."""
        import backend.services.expediente_fetcher as fx
        from backend.database.models import Case
        case = Case(folder_name="2026-00029 X", folder_path=str(tmp_path),
                    radicado_23_digitos="68001333301320260002900", processing_status="COMPLETO")
        db_session.add(case); db_session.commit()
        self._patch_resolve(monkeypatch, "/personal/x/Documents/68001310500420261000900",
                            "68001310500420261000900")
        link = self._FakeLink(case.id, "68001310500420261000900")
        r = fx.fetch_link(db_session, link, dry_run=False)
        assert r["estado"] == "CONFLICTO"
        assert link.estado == "CONFLICTO"
        assert list(tmp_path.iterdir()) == []  # no descargó nada

    def test_typo_mismo_sufijo_no_es_conflicto(self, monkeypatch, db_session, tmp_path):
        """rad con typo de prefijo DANE pero mismo sufijo [5:21] → NO es conflicto."""
        import backend.services.expediente_fetcher as fx
        from backend.database.models import Case
        case = Case(folder_name="2026-00127 Y", folder_path=str(tmp_path),
                    radicado_23_digitos="68432318900120220012700", processing_status="COMPLETO")
        db_session.add(case); db_session.commit()
        # 69432... (typo DANE) mismo sufijo que 68432...
        self._patch_resolve(monkeypatch, "/personal/x/Documents/69432318900120220012700",
                            "69432318900120220012700")
        # mock de la descarga y el registro (no red, no disco real)
        monkeypatch.setattr(fx, "download_file", lambda *a, **k: "deadbeef" * 8)
        import backend.services.sync_service as ss
        monkeypatch.setattr(ss, "sync_case_folder", lambda *a, **k: {"docs_added": 0})
        link = self._FakeLink(case.id, "69432318900120220012700")
        r = fx.fetch_link(db_session, link, dry_run=False)
        assert r["estado"] != "CONFLICTO"  # typo mismo sufijo → pasa el guard
        assert r["estado"] in ("DESCARGADO", "SIN_NOVEDAD")
