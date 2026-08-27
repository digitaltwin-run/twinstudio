"""Audyt łączności: co miało być połączone, a nie jest.

DRC odpowiada na pytanie „czy to, co narysowano, da się wyprodukować".
Nie odpowiada na pytanie „czy czegoś nie zapomniano". Pad bez sieci jest
dla DRC poprawny, a dwie szyny zasilania nazwane `5V` i `+5V` to dla
niego dwie różne, całkowicie legalne sieci — mimo że układ zostaje bez
zasilania. Te reguły czytają netlistę schematu i porównują ją z PCB.
"""
from __future__ import annotations

import re
from typing import Any

# (kod, waga, opis, zalecenie)
_RULES: dict[str, tuple[str, str, str, str]] = {
    "rail_split": (
        "EDA-NET-RAIL-SPLIT-001", "ERROR",
        "Ta sama szyna zasilania występuje pod kilkoma nazwami, więc jej odcinki nie są ze sobą połączone.",
        "Ujednolić nazwę etykiety na wszystkich odcinkach szyny albo połączyć je jawnie na schemacie.",
    ),
    # Zapasowe wyprowadzenie płytki deweloperskiej też daje sieć jednowęzłową.
    # Nazywanie tego błędem uczy ignorowania audytu, a realny przypadek —
    # niepodłączone zasilanie — łapie osobna reguła `no_power` z wagą ERROR.
    "single_node": (
        "EDA-NET-SINGLE-NODE-001", "WARNING",
        "Sieć ma tylko jeden węzeł, czyli pin prowadzi donikąd.",
        "Dociągnąć sieć do drugiego wyprowadzenia albo oznaczyć pin jako świadomie niepodłączony (no_connect).",
    ),
    "floating_pin": (
        "EDA-NET-FLOATING-PIN-001", "ERROR",
        "Pin nie należy do żadnej sieci.",
        "Podłączyć pin albo dodać symbol no_connect, żeby decyzja była udokumentowana.",
    ),
    "no_power": (
        "EDA-NET-NO-POWER-001", "ERROR",
        "Wyprowadzenie zasilania układu nie ma połączenia z żadnym innym elementem.",
        "Dociągnąć pin zasilania do właściwej szyny i sprawdzić nazwę etykiety.",
    ),
    "isolated_part": (
        "EDA-NET-ISOLATED-PART-001", "ERROR",
        "Element jest połączony wyłącznie sam ze sobą — nie łączy się z resztą układu.",
        "Doprowadzić sygnał i masę do elementu albo usunąć go ze schematu.",
    ),
    "undefined_level": (
        "EDA-SIM-UNDEFINED-LEVEL-001", "ERROR",
        "Węzeł stoi w paśmie nieokreślonym wejścia cyfrowego — ani zero, ani jedynka.",
        "Dobrać dzielnik tak, by stan spoczynkowy trafiał poniżej progu niskiego albo powyżej wysokiego; sam pull-up bez pull-downu zwykle wystarcza.",
    ),
    "unmodelled_part": (
        "EDA-SIM-NO-MODEL-001", "WARNING",
        "Element nie ma modelu SPICE, więc symulacja go pomija.",
        "Dodać właściwości modelu do symbolu albo świadomie przyjąć, że wynik opisuje tylko resztę układu.",
    ),
    "drift_missing_part": (
        "EDA-NET-DRIFT-PART-001", "ERROR",
        "Element istnieje tylko po jednej stronie projektu.",
        "Dodać brakujący element albo usunąć zbędny; dopiero potem synchronizować sieci.",
    ),
    "drift_pin_swap": (
        "EDA-NET-DRIFT-PINOUT-001", "WARNING",
        "Ten sam element trafia w schemacie i w PCB na inne wyprowadzenie mikrokontrolera.",
        "Wybrać stronę wiodącą: przypisanie z PCB zwykle wynika z długości ścieżek, a firmware musi znać właśnie je.",
    ),
    "drift_net_name": (
        "EDA-NET-DRIFT-NAME-001", "WARNING",
        "Ta sama linia nazywa się inaczej w schemacie i w PCB.",
        "Ujednolicić nazewnictwo sieci, żeby porównanie obu stron przestało zgłaszać fałszywe różnice.",
    ),
    "drift_unset_pad": (
        "EDA-NET-DRIFT-UNSET-001", "WARNING",
        "Pad w PCB nie ma sieci, choć schemat ją dla tego pinu przewiduje.",
        "Przypisać sieć na padzie albo potwierdzić, że wyprowadzenie zostaje wolne.",
    ),
}

# Pin zasilania rozpoznajemy po nazwie, bo typ `power_in` bywa w bibliotekach
# lokalnych pomijany — tak jest w tym projekcie, gdzie wszystko jest `bidirectional`.
_POWER_PIN = re.compile(r"^(v(cc|dd|ss|bat|in|out)|\+?\d+v\d*|gnd|agnd|dgnd|vref)$", re.IGNORECASE)
_GROUND_PIN = re.compile(r"^(gnd|agnd|dgnd|vss)$", re.IGNORECASE)


def _rail_key(name: str) -> str | None:
    """Sprowadza nazwę szyny do postaci kanonicznej: `+3V3`, `3v3`, `P3V3` → `3V3`."""
    cleaned = name.strip().upper().lstrip("+").replace("P", "", 1) if name.startswith("P") else name.strip().upper().lstrip("+")
    if re.fullmatch(r"GND|AGND|DGND|VSS", cleaned):
        return "GND"
    match = re.fullmatch(r"(\d+)V(\d*)", cleaned)
    if match:
        return f"{match.group(1)}V{match.group(2) or ''}"
    match = re.fullmatch(r"V(CC|DD)", cleaned)
    if match:
        return cleaned
    return None


def _same_family(entry: str) -> str | None:
    """Czy obie nazwy należą do tej samej rodziny sygnałów (np. GP7 vs GP2).

    Wtedy różnica to wybór wyprowadzenia, a nie inna nazwa tej samej linii —
    router mógł przypisać inne GPIO, żeby skrócić ścieżki, i firmware musi
    znać właśnie tę wersję.
    """
    match = re.search(r"PCB (\S+) ≠ schemat (\S+)", entry)
    if not match:
        return None
    left, right = match.group(1), match.group(2)
    prefixes = [re.match(r"^([A-Za-z_+]+)", name) for name in (left, right)]
    if not all(prefixes):
        return None
    return prefixes[0].group(1) if prefixes[0].group(1) == prefixes[1].group(1) else None


def _finding(kind: str, detail: str, samples: list[str]) -> dict[str, Any]:
    code, severity, message, remediation = _RULES[kind]
    return {
        "code": code,
        "severity": severity,
        "category": kind,
        "count": len(samples),
        "message": message,
        "detail": detail,
        "remediation": remediation,
        "samples": samples[:8],
    }


def simulation_state(
    result: dict[str, Any], source: str = ""
) -> dict[str, Any]:
    """Zamienia punkt pracy DC na ustalenia z kodami.

    Napięcie w paśmie nieokreślonym jest błędem doboru elementów, nie
    topologii — dlatego ani DRC, ani audyt łączności go nie widzą, a mimo
    to wejście czyta wtedy przypadkowo.
    """
    findings: list[dict[str, Any]] = []
    thresholds = result.get("thresholds") or {}
    stray = result.get("undefined_logic") or []
    if stray:
        findings.append(_finding(
            "undefined_level",
            f"Próg niski {thresholds.get('low')} V, wysoki {thresholds.get('high')} V.",
            [f"{item.get('node')} = {item.get('volts')} V" for item in stray],
        ))
    skipped = result.get("skipped_devices") or []
    if skipped:
        findings.append(_finding(
            "unmodelled_part",
            "Symulacja opisuje układ bez tych elementów.",
            list(skipped),
        ))
    blocking = any(item["severity"] == "ERROR" for item in findings)
    steps = [f"{item['code']}: {item['remediation']}" for item in findings if item["severity"] == "ERROR"]
    return {
        "schema_id": "twinstudio.eda-simulation-state/v1",
        "status": "blocked" if blocking else "ready",
        "source": {"path": source or result.get("source", ""), "kind": "schematic"},
        "summary": {
            "nodes": len(result.get("voltages") or {}),
            "undefined": len(stray),
            "skipped": len(skipped),
            "driven_rails": list(result.get("driven_rails") or []),
        },
        "codes": list(dict.fromkeys(item["code"] for item in findings)),
        "findings": findings,
        "draft": {
            "schema_id": "twinstudio.eda-repair-draft/v1",
            "status": "draft",
            "requires_approval": True,
            # Poziom w paśmie nieokreślonym to dobór wartości elementów.
            # Automat nie wie, czy usunąć pull-down, czy zmienić rezystory.
            "requires_manual_routing": blocking,
            "message": (
                "To jest wynik symulacji, niezmieniający projektu. Poziom w "
                "paśmie nieokreślonym wynika z doboru wartości, więc poprawkę "
                "trzeba zatwierdzić przed wygenerowaniem kandydata."
            ),
            "repair_steps": steps or ["Symulacja nie zgłasza problemów z poziomami."],
            "prompt": "Przygotuj wyłącznie kandydat naprawy poziomów: " + " ".join(steps),
        },
    }


def netlist_state(
    netlist: dict[str, Any], pcb: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Zamienia netlistę na ustalenia z kodami — tak jak `pcb_state` robi to dla DRC."""
    nets = netlist.get("nets") or []
    components = netlist.get("components") or []
    findings: list[dict[str, Any]] = []
    intentional_no_connect = {
        (str(node.get("reference", "")), str(node.get("pin", "")))
        for entry in netlist.get("intentional_no_connect") or []
        if isinstance(entry, dict)
        for node in entry.get("nodes") or []
        if isinstance(node, dict)
    }

    nodes_by_net = {net.get("name", ""): net.get("nodes") or [] for net in nets}
    seen: dict[str, list[dict[str, str]]] = {}
    for reference in ((node.get("reference", ""), node) for nodes in nodes_by_net.values() for node in nodes):
        seen.setdefault(reference[0], []).append(reference[1])

    # 1. Szyna rozbita na kilka nazw.
    rails: dict[str, list[str]] = {}
    for name in nodes_by_net:
        key = _rail_key(name)
        if key:
            rails.setdefault(key, []).append(name)
    split = {key: sorted(names) for key, names in rails.items() if len(names) > 1}
    if split:
        findings.append(_finding(
            "rail_split",
            "Odcinki tej samej szyny nie są ze sobą połączone.",
            [
                f"{key}: {' | '.join(f'{name} ({len(nodes_by_net[name])} w.)' for name in names)}"
                for key, names in sorted(split.items())
            ],
        ))

    # 2. Sieci jednowęzłowe.
    dangling = sorted(
        f"{name} → {nodes[0]['reference']}.{nodes[0]['pin']}"
        for name, nodes in nodes_by_net.items()
        if len(nodes) == 1
    )
    if dangling:
        findings.append(_finding("single_node", "Sieć kończy się na jednym pinie.", dangling))

    # 3. Piny spoza jakiejkolwiek sieci.
    floating: list[str] = []
    for component in components:
        reference = component.get("reference", "")
        connected = {str(node["pin"]) for node in seen.get(reference, [])}
        connected.update(pin for ref, pin in intentional_no_connect if ref == reference)
        for pin in component.get("pins") or []:
            if str(pin.get("number")) not in connected:
                floating.append(f"{reference}.{pin.get('number')} [{pin.get('name')}]")
    if floating:
        findings.append(_finding("floating_pin", "Pin nie występuje w żadnej sieci.", sorted(floating)))

    # 4. Zasilanie i masa układów scalonych.
    starved: list[str] = []
    for component in components:
        reference = component.get("reference", "")
        for pin in component.get("pins") or []:
            label = pin.get("name") or pin.get("number") or ""
            if not _POWER_PIN.fullmatch(label):
                continue
            net = next(
                (name for name, nodes in nodes_by_net.items()
                 if any(node["reference"] == reference and node["pin"] == pin.get("number") for node in nodes)),
                None,
            )
            if net is None or len(nodes_by_net.get(net, [])) < 2:
                kind = "masa" if _GROUND_PIN.fullmatch(label) else "zasilanie"
                starved.append(f"{reference}.{pin.get('number')} [{label}] — {kind}, sieć {net or 'brak'}")
    if starved:
        findings.append(_finding(
            "no_power", "Pin zasilania lub masy nie ma z czym się połączyć.", sorted(starved)
        ))

    # 5. Elementy zamknięte same w sobie.
    isolated: list[str] = []
    for component in components:
        reference = component.get("reference", "")
        own = [name for name, nodes in nodes_by_net.items()
               if any(node["reference"] == reference for node in nodes)]
        if not own:
            continue
        if all(
            {node["reference"] for node in nodes_by_net[name]} == {reference}
            for name in own
        ):
            isolated.append(f"{reference} (sieci: {', '.join(sorted(own))})")
    if isolated:
        findings.append(_finding(
            "isolated_part", "Element nie ma połączenia z resztą układu.", sorted(isolated)
        ))

    # 6. Rozjazd schematu i PCB.
    if pcb:
        pads = pcb.get("pads") or []
        pcb_refs = {pad["reference"] for pad in pads if pad.get("reference")}
        sch_refs = {component.get("reference", "") for component in components}
        drift = [f"tylko w schemacie: {ref}" for ref in sorted(sch_refs - pcb_refs)]
        drift += [f"tylko w PCB: {ref}" for ref in sorted(pcb_refs - sch_refs)]
        mismatched = sorted(
            f"{pad['reference']}.{pad['pin']}: PCB {pad['net'] or 'brak'} ≠ schemat {expected}"
            for pad in pads
            for expected in [next(
                (name for name, nodes in nodes_by_net.items()
                 if any(node["reference"] == pad["reference"] and node["pin"] == pad["pin"] for node in nodes)),
                None,
            )]
            if expected is not None and expected != (pad.get("net") or "")
        )
        if drift:
            findings.append(_finding(
                "drift_missing_part", "Element bez odpowiednika po drugiej stronie.", drift
            ))
        # Jeden worek „rozjazd" nie mówi, co robić. Ta sama linia pod inną
        # nazwą, ten sam przycisk na innym GPIO i pad bez sieci to trzy różne
        # decyzje, więc rozdzielamy je na trzy ustalenia.
        unset = [item for item in mismatched if ": PCB brak ≠" in item]
        swaps = [
            item for item in mismatched
            if item not in unset and _same_family(item)
        ]
        renames = [item for item in mismatched if item not in unset and item not in swaps]
        for kind, samples, detail in (
            ("drift_pin_swap", swaps, "Ten sam element, inne wyprowadzenie."),
            ("drift_net_name", renames, "Ta sama linia, inna nazwa."),
            ("drift_unset_pad", unset, "Pad w PCB bez sieci."),
        ):
            if samples:
                findings.append(_finding(kind, detail, samples))

    codes = list(dict.fromkeys(item["code"] for item in findings))
    blocking = any(item["severity"] == "ERROR" for item in findings)
    steps = [f"{item['code']}: {item['remediation']}" for item in findings if item["severity"] == "ERROR"]
    return {
        "schema_id": "twinstudio.eda-netlist-state/v1",
        "status": "blocked" if blocking else "ready",
        "source": netlist.get("source", ""),
        "summary": {
            "components": len(components),
            "nets": len(nets),
            "nodes": sum(len(net.get("nodes") or []) for net in nets),
            "findings": len(findings),
        },
        "codes": codes,
        "findings": findings,
        "draft": {
            "schema_id": "twinstudio.eda-repair-draft/v1",
            "status": "draft",
            "requires_approval": True,
            # Łączność wynika z intencji projektanta, nie z geometrii — automat
            # nie zgadnie, do której szyny miał trafić pin. Draft opisuje, co
            # naprawić; zmianę zatwierdza człowiek.
            "requires_manual_routing": blocking,
            "message": (
                "To jest plan diagnostyczny netlisty, niezmieniający projektu. "
                "Braki łączności wynikają z intencji projektanta, więc każdą "
                "poprawkę trzeba zatwierdzić przed wygenerowaniem kandydata."
            ),
            "repair_steps": steps or ["Netlista nie zgłasza braków łączności."],
            "prompt": "Przygotuj wyłącznie kandydat naprawy łączności: " + " ".join(steps),
        },
    }
