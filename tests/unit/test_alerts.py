from interface.backend import alerts

CFG = {"threshold_s": 300, "repeat_s": 1800, "host": "smtp.x", "to": ["a@x.com"], "sender": "s@x.com",
       "user": "", "port": 587, "password": "", "starttls": True}


def root(sid, espera):
    return {"instancia": 1, "sid": sid, "serial": 7, "segundos_espera": espera, "sesiones_bloqueadas": 2}


def test_no_alerta_por_debajo_del_umbral():
    n = {}
    assert alerts.plan_alerts([root(1, 299)], n, 0, 300, 1800) == ([], [])
    assert n == {}


def test_avisa_una_vez_y_repite_tras_el_intervalo():
    n = {}
    assert len(alerts.plan_alerts([root(1, 400)], n, 0, 300, 1800)[0]) == 1
    assert alerts.plan_alerts([root(1, 460)], n, 60, 300, 1800)[0] == []
    assert len(alerts.plan_alerts([root(1, 2200)], n, 1800, 300, 1800)[0]) == 1


def test_detecta_liberacion():
    n = {}
    alerts.plan_alerts([root(1, 400)], n, 0, 300, 1800)
    to_alert, released = alerts.plan_alerts([], n, 60, 300, 1800)
    assert to_alert == [] and released == ["1:1,7"] and n == {}


def test_tick_sin_smtp_no_envia():
    sent = []
    cfg = {**CFG, "host": ""}
    assert alerts.tick(cfg, {}, lambda: [root(1, 900)], sent.append) == 0 and not sent


def test_tick_envia_y_reintenta_si_falla():
    n = {}

    def boom(cfg, msg):
        raise OSError("smtp caído")

    try:
        alerts.tick(CFG, n, lambda: [root(1, 900)], boom)
    except OSError:
        pass
    assert n == {}
    sent = []
    assert alerts.tick(CFG, n, lambda: [root(1, 900)], lambda c, m: sent.append(m)) == 1
    assert "Bloqueo de más de 5 min" in sent[0]["Subject"]
