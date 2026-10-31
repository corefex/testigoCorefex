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
# The committed demo policy. Never overwritten by the interface: a mandate
# recorded and signed live (view 1) goes to ACTIVE_POLICY under RUNS_DIR.
POLICY_PATH = ROOT / "policy" / "marta.policy.yaml"
ACTIVE_POLICY = Path("policy") / "active.policy.yaml"     # relative to RUNS_DIR (git-ignored)

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


def active_policy_path():
    """Where a policy signed from the interface (view 1) is written."""
    return _root_path(get("RUNS_DIR")) / ACTIVE_POLICY


class PolicyNotTrusted(Exception):
    """The policy signed from the interface is on disk but cannot be trusted
    (its stored hash or its owner signature does not check). Every consumer
    stops: it never falls back to the committed policy silently."""


def runs_label(path):
    """A path as messages show it: relative to the repo, or under "RUNS_DIR/",
    never absolute."""
    path = Path(path)
    runs = _root_path(get("RUNS_DIR"))
    for base, prefix in ((runs, "RUNS_DIR/"), (ROOT, "")):
        try:
            return prefix + path.resolve().relative_to(base.resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return path.name


def owner_pubkey():
    """The owner's Ed25519 public key (32 bytes), from the key on this machine
    (SIGNING_KEY_PATH; the same key pair as the receipts, F1-D3), or None."""
    from receipts import keys
    key = _root_path(get("SIGNING_KEY_PATH"))
    return keys.public_from_seed(keys.load_seed(key)) if key.is_file() else None


def archived_policy_path(sha256):
    """Every policy signed here is also kept by its hash, so a receipt signed
    under an earlier policy still verifies after a new one is signed."""
    return active_policy_path().parent / ("%s.policy.yaml" % sha256)


def _is_sha(text):
    return isinstance(text, str) and len(text) == 64 and all(c in "0123456789abcdef" for c in text)


def trusted_signed_policy(path, pubkey=None, want_sha=None):
    """Load a policy signed from the interface and check it: its stored hash
    matches its content (and `want_sha`, if given) and its signature verifies
    under the owner's public key. Returns the Policy or raises PolicyNotTrusted."""
    from interceptor.policy import load
    label = runs_label(path)
    try:
        pol = load(path)
    except Exception as e:  # noqa: BLE001 - unreadable is untrusted
        raise PolicyNotTrusted("%s cannot be read (%s)" % (label, type(e).__name__))
    if not pol.hash_matches_stored():
        raise PolicyNotTrusted("%s: its stored sha256 does not match its content" % label)
    if want_sha is not None and pol.sha256() != want_sha:
        raise PolicyNotTrusted("%s is not the policy %s…" % (label, want_sha[:12]))
    pubkey = pubkey if pubkey is not None else owner_pubkey()
    if pubkey is None:
        raise PolicyNotTrusted("%s: no owner key on this machine to check its signature "
                               "(SIGNING_KEY_PATH)" % label)
    if not pol.signature_valid(pubkey):
        raise PolicyNotTrusted("%s: not signed by the owner's key" % label)
    return pol


def archive_policy(path):
    """Copy a trusted signed policy file to RUNS_DIR/policy/<sha256>.policy.yaml
    (atomically, once). Returns the archive path."""
    import tempfile
    from interceptor.policy import load
    data = Path(path).read_bytes()
    dest = archived_policy_path(load(path).sha256())
    if dest.is_file() and dest.read_bytes() == data:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".archive-", suffix=".yaml", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


def policy_path():
    """The policy every consumer enforces and shows: the service (/api/policy,
    /status), the loop, the bench and `testigo verify`. The one signed live from
    the interface when present (RUNS_DIR/policy/active.policy.yaml), else the
    committed policy/marta.policy.yaml.

    The active policy is used only if its stored hash matches and it is signed
    by the owner's key; otherwise PolicyNotTrusted (fail closed, never the
    committed policy instead). A trusted one is also archived by its hash."""
    active = active_policy_path()
    if not active.is_file():
        return POLICY_PATH
    trusted_signed_policy(active)
    archive_policy(active)
    return active


def find_policy_by_hash(sha256, pubkey=None):
    """(Policy, label) for the policy whose sha256 is `sha256`: the committed
    policy (trusted by its hash: it is in the repository), else the one signed
    here and archived by hash, else the active one, both checked like
    trusted_signed_policy. Raises PolicyNotTrusted when none is found or trusted."""
    from interceptor.policy import load
    if not _is_sha(sha256):
        raise PolicyNotTrusted("the receipt names no policy sha256")
    committed = load(POLICY_PATH)
    if committed.sha256() == sha256:
        return committed, runs_label(POLICY_PATH)
    errors = []
    for path in (archived_policy_path(sha256), active_policy_path()):
        try:
            if load(path).sha256() != sha256:
                continue                   # the active policy is another one
        except Exception:  # noqa: BLE001 - missing or unreadable: not this one
            if not path.is_file():
                continue
        try:
            return trusted_signed_policy(path, pubkey, want_sha=sha256), runs_label(path)
        except PolicyNotTrusted as e:
            errors.append(str(e))
    if errors:
        raise PolicyNotTrusted(errors[0])
    raise PolicyNotTrusted("no policy with sha256 %s… (committed or signed here)" % sha256[:12])


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
