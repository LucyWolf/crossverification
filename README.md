# CrossVerification

**Let one Discord bot honour another one's vetting — without either side handing over a
member list.**

A community vets its members. Age checks, account ownership, an application, a voice
interview — whatever their bar is — and hands out a role for it. A partner community trusts
that work, but cannot see it. So everyone goes through the same process a second time, and
the moderators of both sides do the same job twice.

CrossVerification is a small HTTP protocol for exactly that gap. One side asks *"do you
vouch for this user?"*, the other answers *yes* or *no*. That is the whole protocol.

```
POST /coop/check     key=<pairing key>&user_id=<discord id>
→ { "verified": true }
```

- **[SPEC.md](SPEC.md)** — the protocol. Implement against this, in any language.
- **`crossverification/`** — a reference implementation in Python, both halves, no
  framework and no Discord library required.
- **`examples/`** — the complete wiring for a FastAPI issuer and a discord.py relying bot.

It came out of [phobos-bot](https://github.com/LucyWolf/phobos-bot), which has been running
this between installations for a while. It is written down separately so other bots can
speak it too — nothing in it is specific to any one bot.

---

## The two sides

| | |
|---|---|
| **Issuer** | did the vetting, answers questions about it, issues the key |
| **Relying party** | asks, and grants something based on the answer |

A pairing goes one way. Two communities that trust each other both ways set up two
pairings with two keys — because trust is rarely symmetric, and revoking one direction must
not take the other one with it.

## Answering (issuer)

```python
from crossverification import answer_check, Partner, key_hash, RateLimiter

limiter = RateLimiter()

def find_partner(key):
    # you stored the HASH, not the key
    return my_pairings.get(key_hash(key))

def holds_role(user_id, partner):
    member = guild.get_member(int(user_id))
    return bool(member) and {str(r.id) for r in member.roles} & partner.shared_roles

# in your POST /coop/check route:
answer = await answer_check(key, user_id, find_partner, holds_role, limiter)
return JSONResponse(answer.body, status_code=answer.status)
```

That is all of it. The callbacks may be sync or async. The full route, including the
`/coop/info` one, is in [`examples/fastapi_issuer.py`](examples/fastapi_issuer.py).

## Asking (relying party)

```python
from crossverification import ask_partner, Outcome

result = await ask_partner("https://partner.example.com", key, member.id)

if result.outcome is Outcome.VERIFIED:
    await member.add_roles(role)
elif result.outcome is Outcome.NOT_VERIFIED:
    await member.remove_roles(role)      # a clear no, and only a clear no
elif result.pairing_broken:
    tell_an_admin(result.detail)         # the key was rejected - this needs a human
# anything else: leave it alone and ask again later
```

`ask_partner` never raises. For a bot that is not asyncio, `ask_partner_sync` does the same
thing with the standard library only.

## What it refuses to do

These are decisions, not omissions — the reasoning for each is in the spec.

- **No member lists.** There is no endpoint that enumerates anybody. Every question is about
  one user id the asker already has.
- **No personal data.** No names, no roles, no reasons, no dates. The answer is one bit.
- **An unknown key looks exactly like an unknown person.** Otherwise the endpoint becomes a
  way to find valid keys by trying.
- **Everything unclear is a no.** Timeout, DNS failure, HTTP 500, a redirect, an
  unparseable body — all of it. Granting something because a request ended badly is the
  opposite of what a verification is for, and there is no retry-until-yes.
- **No transitive trust.** An answer covers what *this* issuer vetted. A trusts B and B
  trusts C does not make C's verifications valid for A.
- **No central registry.** Nothing to sign up for, nobody to ask for permission.

The relying side also refuses addresses that resolve into private networks — every address a
name resolves to, not just the first. Without that check, the pairing form would double as a
tool for scanning the issuer's own network.

## Before you set one up

A `true` tells another community that a real person is known here and holds a certain role.
That is a statement about somebody, made to a third party. Make sure your members know that
holding the role is what gets shared, and only share roles where that is defensible. The
protocol keeps the payload to a minimum; it cannot decide for you whether the pairing should
exist at all.

## Tests

```bash
python3 tests/test_core.py
```

No network, no dependencies. 67 checks, most of them about what must *not* appear in an
answer.

## Status

Protocol version **1.0**. Field names, status codes and their meanings will not change
within version 1; new optional fields may appear and unknown ones must be ignored. A
breaking change would get a new path prefix so both can be served at once.

Issues and implementations in other languages are welcome. If you build one, the
conformance list in [SPEC.md §10](SPEC.md) is what to aim at.

## Licence

MIT — see [LICENSE](LICENSE). A protocol nobody is allowed to implement is not a protocol.

---
---

# CrossVerification (deutsch)

**Ein Discord-Bot erkennt die Prüfung eines anderen an — ohne dass eine Seite ihre
Mitgliederliste herausgibt.**

Eine Community prüft ihre Leute: Alter, Kontobesitz, eine Bewerbung, ein Gespräch — was auch
immer ihr Maßstab ist — und vergibt eine Rolle dafür. Eine befreundete Community vertraut
dieser Arbeit, kann sie aber nicht sehen. Also läuft jeder dasselbe Verfahren ein zweites
Mal durch, und beide Mod-Teams machen dieselbe Arbeit doppelt.

Genau dafür ist CrossVerification da. Eine Seite fragt *„stehst du für diese Person ein?"*,
die andere antwortet *ja* oder *nein*. Mehr ist es nicht.

```
POST /coop/check     key=<Schlüssel>&user_id=<Discord-ID>
→ { "verified": true }
```

- **[SPEC.md](SPEC.md)** — das Protokoll. Dagegen baut man, in jeder Sprache.
- **`crossverification/`** — eine Umsetzung in Python, beide Seiten, ohne Web-Framework und
  ohne Discord-Bibliothek.
- **`examples/`** — die vollständige Verdrahtung für einen FastAPI-Beantworter und einen
  fragenden discord.py-Bot.

Entstanden ist es in [phobos-bot](https://github.com/LucyWolf/phobos-bot), wo es seit einer
Weile zwischen Installationen läuft. Aufgeschrieben wurde es getrennt, damit andere Bots es
auch sprechen können — nichts daran hängt an einem bestimmten Bot.

## Die zwei Seiten

| | |
|---|---|
| **Beantworter** | hat geprüft, beantwortet Fragen dazu, gibt den Schlüssel aus |
| **Fragender** | fragt und vergibt auf die Antwort hin etwas |

Eine Paarung geht in eine Richtung. Wer sich gegenseitig vertraut, richtet zwei ein, mit
zwei Schlüsseln — Vertrauen ist selten symmetrisch, und eine Richtung zurückzuziehen darf
die andere nicht mitnehmen.

## Was es bewusst nicht kann

Das sind Entscheidungen, keine Lücken; die Begründung steht jeweils in der Spezifikation.

- **Keine Mitgliederlisten.** Es gibt keine Abfrage, die irgendwen aufzählt. Jede Frage geht
  um eine ID, die der Fragende schon hat.
- **Keine Personendaten.** Keine Namen, keine Rollen, keine Gründe. Die Antwort ist ein Bit.
- **Ein falscher Schlüssel sieht aus wie eine unbekannte Person.** Sonst wird die Abfrage
  zum Werkzeug, um gültige Schlüssel zu erraten.
- **Alles Unklare ist ein Nein.** Zeitüberschreitung, Namensauflösung weg, HTTP 500, eine
  Weiterleitung, unlesbare Antwort. Etwas zu vergeben, weil eine Anfrage schiefging, ist das
  Gegenteil dessen, wofür eine Prüfung da ist.
- **Kein weitergereichtes Vertrauen.** Eine Antwort deckt das ab, was *dieser* Beantworter
  geprüft hat. A vertraut B und B vertraut C macht C nicht gültig für A.
- **Keine zentrale Stelle.** Nichts anzumelden, niemanden zu fragen.

Die fragende Seite lehnt außerdem Adressen ab, die in private Netze zeigen — und zwar jede
Adresse, auf die ein Name auflöst, nicht nur die erste. Ohne diese Prüfung wäre das
Einrichtungsformular ein Werkzeug, um das Netz des Partners abzutasten.

## Bevor du eine Paarung einrichtest

Ein `true` sagt einer fremden Community, dass eine echte Person hier bekannt ist und eine
bestimmte Rolle trägt. Das ist eine Aussage über einen Menschen gegenüber Dritten. Sorg
dafür, dass deine Leute wissen, dass das Tragen der Rolle geteilt wird, und teile nur
Rollen, bei denen das vertretbar ist. Das Protokoll hält die Antwort so klein wie möglich —
ob die Paarung überhaupt bestehen soll, kann es dir nicht abnehmen.
