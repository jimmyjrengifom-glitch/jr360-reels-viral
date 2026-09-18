"""Comprueba el camino de descarga: Apify primero, yt-dlp de respaldo.

No toca la red. yt_dlp se sustituye por un doble porque solo hace falta
para importar el módulo.
"""
import sys, types, importlib
from pathlib import Path

sys.modules.setdefault("yt_dlp", types.SimpleNamespace(YoutubeDL=object))
sys.path.insert(0, str(Path(__file__).parent))
app = importlib.import_module("app")


def test_los_datos_de_apify_se_traducen_a_lo_que_espera_n8n():
    m = app._metadatos_apify({"videoPlayCount": 120000, "likesCount": 8300,
                              "commentsCount": 640, "caption": "hola"})
    assert (m["views"], m["likes"], m["comments"]) == (120000, 8300, 640)
    assert m["source"] == "apify" and m["captured_at"].endswith("Z")


def test_si_falta_el_conteo_de_reproducciones_se_usa_el_otro_campo():
    assert app._metadatos_apify({"videoViewCount": 900})["views"] == 900
    # un texto donde debería ir un número no se cuela como métrica
    assert app._metadatos_apify({"likesCount": "muchos"})["likes"] is None


def test_sin_token_de_apify_se_va_directo_a_yt_dlp(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "APIFY_TOKEN", "")
    llamado = {}
    monkeypatch.setattr(app, "_download", lambda url, d: (llamado.setdefault("url", url), (tmp_path/"v.mp4", {}))[1])
    app._obtener_video("https://www.instagram.com/reel/abc/", tmp_path)
    assert llamado["url"].endswith("/reel/abc/")


def test_un_link_que_no_es_de_instagram_no_gasta_apify(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "APIFY_TOKEN", "hay-token")
    monkeypatch.setattr(app, "_download_apify", lambda *a: (_ for _ in ()).throw(AssertionError("no debía llamarse")))
    monkeypatch.setattr(app, "_download", lambda url, d: (tmp_path/"v.mp4", {"source": "yt-dlp"}))
    _, meta = app._obtener_video("https://www.youtube.com/watch?v=x", tmp_path)
    assert meta["source"] == "yt-dlp"


def test_si_apify_falla_el_video_sigue_bajando_con_yt_dlp(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "APIFY_TOKEN", "hay-token")
    monkeypatch.setattr(app, "_download_apify", lambda *a: (_ for _ in ()).throw(RuntimeError("apify caído")))
    monkeypatch.setattr(app, "_download", lambda url, d: (tmp_path/"v.mp4", {"source": "yt-dlp"}))
    _, meta = app._obtener_video("https://www.instagram.com/reel/abc/", tmp_path)
    assert meta["source"] == "yt-dlp"


def test_un_video_gigante_se_corta_y_no_cae_al_respaldo(monkeypatch, tmp_path):
    # OverflowError significa "pesa demasiado", no "Apify falló": reintentar con
    # yt-dlp solo gastaría tiempo para volver a pasarse del tope.
    monkeypatch.setattr(app, "APIFY_TOKEN", "hay-token")
    monkeypatch.setattr(app, "_download_apify", lambda *a: (_ for _ in ()).throw(OverflowError("muy grande")))
    monkeypatch.setattr(app, "_download", lambda url, d: (tmp_path/"v.mp4", {"source": "yt-dlp"}))
    try:
        app._obtener_video("https://www.instagram.com/reel/abc/", tmp_path)
        assert False, "debía propagarse"
    except OverflowError:
        pass
