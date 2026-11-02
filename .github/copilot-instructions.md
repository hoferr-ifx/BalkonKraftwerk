# Projekt-Richtlinien: Anker Solarbank 2 E1600 Pro Agent

## Tech-Stack & Bibliotheken
- Nutze Python 3.12+ mit `asyncio` und `aiohttp`.
- Verwende ausschließlich die Bibliothek `anker-solix-api` (Import über `from api import api` oder `anker_solix_api`, je nach Paketversion – prüfe installierte Signatur).
- Nutze `python-dotenv` für Credentials (`ANKER_USER`, `ANKER_PASSWORD`, `ANKER_COUNTRY="AT"`).
- Nutze `rich` (Live-Display & Tables) für das Terminal-Dashboard.

## Cloud-Abfrage-Regeln (Wichtig!)
- Ein Abfrage-Intervall darf NIEMALS kürzer als 60 Sekunden sein (Anker Rate-Limiting!).
- Nutze `update_sites()` für Live-Leistungsdaten (Solar-Erzeugung, Hausverbrauch, Akku-Ladezustand, Smart Meter Werte).
- Nutze `update_device_details()` maximal alle 10–15 Minuten, um API-Sperren zu vermeiden.
- Implementiere sauberes Exception-Handling für Token-Ablauf und Verbindungsabbrüche.
- Logge alle relevanten Ereignisse und Fehler mit `rich` für eine übersichtliche Darstellung im Terminal.
- Stelle sicher, dass sensible Informationen wie Passwörter oder Tokens niemals geloggt werden.
- Verwende `try`/`except` Blöcke, um Fehler abzufangen und nur relevante Informationen zu loggen.
- Achte darauf, dass alle asynchronen Funktionen korrekt mit `await` aufgerufen werden, um unerwartete Fehler zu vermeiden.
- Verwende `async with` für asynchrone Kontextmanager, um Ressourcen korrekt freizugeben.
- Stelle sicher, dass alle Netzwerkaufrufe innerhalb von `async with` Blöcken erfolgen, um Verbindungslecks zu vermeiden.
- Prüfe regelmäßig, ob alle asynchronen Tasks korrekt beendet werden, um hängende Tasks zu vermeiden.
- Verwende `asyncio.gather` oder `asyncio.create_task` mit Bedacht, um parallele Tasks zu verwalten und sicherzustellen, dass sie korrekt abgeschlossen werden.
- Achte darauf, dass bei Verwendung von `asyncio.create_task` die erstellten Tasks überwacht und bei Bedarf abgebrochen werden, um Ressourcenlecks zu vermeiden.
- Stelle sicher, dass alle Tasks, die `asyncio.create_task` verwenden, in einer zentralen Task-Liste verwaltet werden, um eine einfache Überwachung und Kontrolle zu ermöglichen.
- Implementiere Mechanismen zum sauberen Abbruch und Aufräumen von Tasks beim Beenden des Programms, um Ressourcenlecks zu vermeiden.
- Stelle sicher, dass alle asynchronen Tasks ordnungsgemäß auf Fehler überprüft werden, um unerwartete Abstürze zu vermeiden.
- Implementiere Logging für alle abgefangenen Fehler, um die Fehlerdiagnose zu erleichtern.
- Stelle sicher, dass alle asynchronen Funktionen, die externe Ressourcen verwenden, ordnungsgemäß freigegeben werden, um Speicher- und Ressourcenlecks zu vermeiden.
- Implementiere Mechanismen zum sauberen Schließen von Netzwerkverbindungen und Sessions, um Verbindungslecks zu vermeiden.
