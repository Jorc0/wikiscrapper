"""Cliente HTTP educado para Wikimedia, Wikidata y GBIF.

- Una sola petición a la vez y una pausa mínima entre peticiones.
- maxlag=5 en las APIs de MediaWiki: si los servidores van con retraso, esperamos.
- Respeta 429/503 y Retry-After con backoff exponencial.
"""
import logging
import time

import requests

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


def _retry_after(resp, default):
    value = resp.headers.get("Retry-After", "")
    return int(value) if value.isdigit() else default


class Client:
    def __init__(self, user_agent, min_interval=1.0, maxlag=5, max_attempts=6):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip"})
        self.min_interval = min_interval
        self.maxlag = maxlag
        self.max_attempts = max_attempts
        self._last = 0.0

    def _wait(self):
        delay = self._last + self.min_interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def get(self, url, params=None, *, stream=False, timeout=60):
        max_attempts = self.max_attempts
        for attempt in range(max_attempts):
            self._wait()
            try:
                resp = self.session.get(url, params=params, stream=stream, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                delay = 5 * 2 ** attempt
                log.warning("Error de red (%s). Reintento en %ss", e, delay)
                time.sleep(delay)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = _retry_after(resp, 5 * 2 ** attempt)
                log.warning("HTTP %s en %s. Esperando %ss", resp.status_code, url, delay)
                resp.close()
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        raise ApiError(f"No se pudo obtener {url} tras {max_attempts} intentos")

    def api(self, url, **params):
        """Llamada a una API MediaWiki (Commons o Wikidata) con maxlag y formato JSON v2."""
        params.update(format="json", formatversion="2", maxlag=self.maxlag)
        for attempt in range(8):
            resp = self.get(url, params)
            data = resp.json()
            err = data.get("error")
            if not err:
                return data
            if err.get("code") == "maxlag":
                delay = _retry_after(resp, 5)
                log.info("Servidores con retraso (maxlag). Esperando %ss", delay)
                time.sleep(delay)
                continue
            if err.get("code") in ("ratelimited", "toomanyrequests", "cirrussearch-too-busy-error"):
                time.sleep(10 * (attempt + 1))
                continue
            raise ApiError(f"{err.get('code')}: {err.get('info')}")
        raise ApiError(f"La API sigue saturada tras varios intentos: {url}")

    def api_all(self, url, **params):
        """Itera sobre todas las páginas de una consulta con 'continue'."""
        cont = {}
        while True:
            data = self.api(url, **params, **cont)
            yield data
            if "continue" not in data:
                return
            cont = data["continue"]

    def download(self, url, path):
        """Descarga a un fichero temporal y lo renombra al terminar, para no dejar ficheros a medias."""
        tmp = path.with_suffix(path.suffix + ".part")
        resp = self.get(url, stream=True, timeout=120)
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        tmp.replace(path)
