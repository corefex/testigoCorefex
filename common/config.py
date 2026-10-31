"""Configuration: the only place that reads the environment.

Values come from the process environment, then from `.env` at the repo root
(never overriding what is already set). Every variable the code reads is listed
in ENV_VARS, and a test checks that list against `.env.example`.

Paths are resolved from the repo root, so commands work from any directory.
"""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "policy" / "marta.policy.yaml"

# The shop's profile (simulated, R2): where Marta's supplier orders are
# delivered. The mandate names the shop ("la tienda", "Tienda Doña Marta") but
# never dictates its address; policy.compile binds the name to this address
# (F1-D2), and the portal starts every order with it.
SHOP = {
    "name": "Tienda Doña Marta",
    "address": "Calle 45 # 12-30, Bogotá",
    "simulated": True,
}

# Every variable read from the environment, with its default ("" = no default).
ENV_VARS = {
    "META_API_BASE_URL": "",
    "META_API_KEY": "",
    "META_MODEL_WONDER": "",
    "META_MODEL_SPARK": "",
    "META_MODEL_SAM": "",
    "META_MODEL_VOICE": "",
    "GLIMMER_BASE_URL": "",
    "GLIMMER_MODEL": "",
    "PORTAL_HOST": "127.0.0.1",
    "PORTAL_PORT": "8080",
    "INTERCEPTOR_HOST": "127.0.0.1",
    "INTERCEPTOR_PORT": "8090",
    "UI_ORIGIN": "http://localhost:8090",
    "WEBAUTHN_RP_ID": "localhost",
    "SCORER_TOKEN": "",
    "SIGNING_KEY_PATH": ".secrets/receipts.key",
    "RUNS_DIR": "runs",
    "MAX_SPEND_USD": "20",
}

# Variables reported as set/empty by doctor and the status page (never their values).
MODEL_VARS = ("META_API_BASE_URL", "META_API_KEY", "META_MODEL_WONDER",
              "META_MODEL_SPARK", "META_MODEL_SAM", "META_MODEL_VOICE", "GLIMMER_BASE_URL")

_loaded = False


def configured(names=MODEL_VARS):
    """{name: True/False} for whether each variable has a value. Never returns values."""
    return {n: bool(get(n)) for n in names}


def load_env(path=None):
    """Load `.env` once. Existing environment variables win."""
    global _loaded
    if _loaded and path is None:
        return
    env_file = Path(path) if path else ROOT / ".env"
    if env_file.is_file():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file, override=False)
        except ImportError:
            _load_plain(env_file)
    _loaded = True


def _load_plain(env_file):
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


def get(name):
    if name not in ENV_VARS:
        raise KeyError("%s is not a declared variable (add it to ENV_VARS and .env.example)" % name)
    load_env()
    val = os.environ.get(name, "")
    return val if val != "" else ENV_VARS[name]


def _root_path(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


@dataclass(frozen=True)
class Settings:
    meta_base_url: str
    meta_api_key: str
    model_wonder: str
    model_spark: str
    model_sam: str
    model_voice: str
    glimmer_base_url: str
    glimmer_model: str
    portal_host: str
    portal_port: int
    interceptor_host: str
    interceptor_port: int
    ui_origin: str
    webauthn_rp_id: str
    scorer_token: str
    signing_key_path: Path
    runs_dir: Path
    max_spend_usd: float

    @property
    def portal_url(self):
        return "http://%s:%d" % (self.portal_host, self.portal_port)

    def missing(self, *names):
        """Return the env var names, among `names`, that have no value in these settings."""
        return [n for n in names if not getattr(self, FIELD_OF[n])]


FIELD_OF = {
    "META_API_BASE_URL": "meta_base_url", "META_API_KEY": "meta_api_key",
    "META_MODEL_WONDER": "model_wonder", "META_MODEL_SPARK": "model_spark",
    "META_MODEL_SAM": "model_sam", "META_MODEL_VOICE": "model_voice",
    "GLIMMER_BASE_URL": "glimmer_base_url", "GLIMMER_MODEL": "glimmer_model",
    "SCORER_TOKEN": "scorer_token",
}


def settings():
    return Settings(
        meta_base_url=get("META_API_BASE_URL"),
        meta_api_key=get("META_API_KEY"),
        model_wonder=get("META_MODEL_WONDER"),
        model_spark=get("META_MODEL_SPARK"),
        model_sam=get("META_MODEL_SAM"),
        model_voice=get("META_MODEL_VOICE"),
        glimmer_base_url=get("GLIMMER_BASE_URL"),
        glimmer_model=get("GLIMMER_MODEL"),
        portal_host=get("PORTAL_HOST"),
        portal_port=int(get("PORTAL_PORT")),
        interceptor_host=get("INTERCEPTOR_HOST"),
        interceptor_port=int(get("INTERCEPTOR_PORT")),
        ui_origin=get("UI_ORIGIN"),
        webauthn_rp_id=get("WEBAUTHN_RP_ID"),
        scorer_token=get("SCORER_TOKEN"),
        signing_key_path=_root_path(get("SIGNING_KEY_PATH")),
        runs_dir=_root_path(get("RUNS_DIR")),
        max_spend_usd=float(get("MAX_SPEND_USD")),
    )
