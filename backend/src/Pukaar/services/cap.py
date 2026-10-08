from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET


CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
ET.register_namespace("", CAP_NS)


SEVERITY_MAP = {
    "green": "Minor",
    "yellow": "Minor",
    "orange": "Moderate",
    "red": "Severe",
    "info": "Minor",
    "minor": "Minor",
    "moderate": "Moderate",
    "severe": "Severe",
}


def _cap(parent: ET.Element, name: str, text: Any) -> ET.Element:
    child = ET.SubElement(parent, f"{{{CAP_NS}}}{name}")
    child.text = "" if text is None else str(text)
    return child


def build_cap_xml(event: dict[str, Any]) -> str:
    now = event.get("sent") or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    identifier = event.get("identifier") or f"pukaar-{hashlib.sha256(repr(event).encode()).hexdigest()[:16]}"
    severity = SEVERITY_MAP.get(str(event.get("severity", "minor")).lower(), "Minor")
    lat = event.get("lat", -34.6037)
    lon = event.get("lon", -58.3816)
    radius = float(event.get("radius_m", 500.0))
    delta = radius / 111320.0
    polygon = event.get("polygon") or (
        f"{lat-delta:.6f},{lon-delta:.6f} {lat-delta:.6f},{lon+delta:.6f} "
        f"{lat+delta:.6f},{lon+delta:.6f} {lat+delta:.6f},{lon-delta:.6f} {lat-delta:.6f},{lon-delta:.6f}"
    )

    alert = ET.Element(f"{{{CAP_NS}}}alert")
    _cap(alert, "identifier", identifier)
    _cap(alert, "sender", event.get("sender", "Pukaar@demo.local"))
    _cap(alert, "sent", now)
    _cap(alert, "status", event.get("status", "Actual"))
    _cap(alert, "msgType", event.get("msgType", "Alert"))
    _cap(alert, "scope", event.get("scope", "Restricted"))
    _cap(alert, "code", "SINAGIR-compatible")
    _cap(alert, "note", "Experimental complementary system; does not replace official weather or Civil Defense channels.")

    info = ET.SubElement(alert, f"{{{CAP_NS}}}info")
    _cap(info, "language", event.get("language", "en-US"))
    _cap(info, "category", "Met")
    _cap(info, "event", event.get("event", "Flood"))
    _cap(info, "responseType", "Monitor")
    _cap(info, "urgency", event.get("urgency", "Expected"))
    _cap(info, "severity", severity)
    _cap(info, "certainty", event.get("certainty", "Likely"))
    _cap(info, "senderName", "Pukaar")
    _cap(info, "headline", event.get("headline", "Possible flood alert"))
    _cap(info, "description", event.get("description", event.get("summary", "Local signals indicate hydrometeorological risk.")))
    _cap(info, "instruction", event.get("instruction", "Monitor the area and validate with Civil Defense before public dissemination."))
    _cap(info, "web", event.get("web", "https://www.argentina.gob.ar/sinagir"))

    signature = hashlib.sha256(ET.tostring(alert, encoding="utf-8")).hexdigest()
    parameter = ET.SubElement(info, f"{{{CAP_NS}}}parameter")
    _cap(parameter, "valueName", "pukaar-signature-sha256")
    _cap(parameter, "value", signature)

    area = ET.SubElement(info, f"{{{CAP_NS}}}area")
    _cap(area, "areaDesc", event.get("areaDesc", event.get("site_id", "Pukaar Pukaar operational area")))
    _cap(area, "polygon", polygon)
    geocode = ET.SubElement(area, f"{{{CAP_NS}}}geocode")
    _cap(geocode, "valueName", "SINAGIR/SINAME site")
    _cap(geocode, "value", event.get("site_id", "demo-site"))
    return ET.tostring(alert, encoding="utf-8", xml_declaration=True).decode("utf-8")
