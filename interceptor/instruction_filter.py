"""F5: does a line of divergent text look like an instruction for the agent?

The divergence check finds text that is in one channel (page code / pixels) and
not the other. Most such text is legitimate: collapsed menus, screen-reader
labels, promos. Only text that reads as an instruction aimed at the agent
should raise the alarm, or TESTIGO+ would block normal pages (false positives).

A line is flagged if, in English or Spanish, it has any of these signals (F5-D1):
  - a street address (Calle/Carrera/... number # number - number; a line
    carrying an address that appears in only one channel is suspicious
    whatever the address);
  - a term that addresses an agent together with a delivery or confirmation
    verb (or a change of the delivery address).

Known limit (F5-D4): an instruction written without any of these signals would
not be flagged. It is assumed and measured (a WitnessBench case), not hidden.
"""

import re

from common.address import ADDRESS_RE

# Terms that address an agent, in English and Spanish (matched as whole words).
AGENT_TERMS = (
    "agent", "agents", "assistant", "assistants", "ai assistant", "ai agent",
    "system note for agents", "agente", "agentes", "asistente", "asistentes",
    "ia", "bot", "bots",
)

# Delivery / confirmation / change-of-destination verbs, in English and Spanish.
ACTION_VERBS = (
    "deliver", "ship", "send", "confirm",
    "change the delivery address", "change delivery address", "change the address",
    "update the delivery address", "update the address", "set the address",
    "entrega", "entregar", "envía", "envia", "enviar", "confirma", "confirmar",
    "cambia la dirección", "cambia la direccion", "cambiar la dirección",
    "actualiza la dirección", "actualiza la direccion", "actualizar la dirección",
)


# Agent terms match as whole words ("ia" is not in "diaria" or "vía", "bot" is
# not in "botella" or "botón"); a multi-word term allows any spacing.
_AGENT_RE = re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(
    r"\s+".join(re.escape(w) for w in term.split())
    for term in sorted(AGENT_TERMS, key=len, reverse=True)))


def looks_like_instruction(text):
    """True when a divergent line reads as an instruction aimed at the agent."""
    t = " ".join(str(text or "").split())
    if not t:
        return False
    if ADDRESS_RE.search(t):
        return True
    t = t.lower()
    if _AGENT_RE.search(t) and any(v in t for v in ACTION_VERBS):
        return True
    return False


def filter_instructions(lines):
    """Keep only the lines that look like an instruction."""
    return [x for x in lines if looks_like_instruction(x)]
