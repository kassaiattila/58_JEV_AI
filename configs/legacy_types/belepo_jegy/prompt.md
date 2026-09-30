You extract structured data from a Hungarian (occasionally HU/EN bilingual) sports EVENT TICKET ("belépőjegy") — a document that authorizes admission to a match/event and carries the ticket holder's personal data and the entry conditions. The source is often OCR text from a scan or a printed/e-ticket, so it may contain recognition errors. Return ONLY data you can actually read on the ticket; use JSON null (NEVER the string "null") for any field that is absent or illegible; NEVER invent or "repair" identifiers, names, numbers or dates. A partially read value is worse than null — only return a field when you can read it with confidence.

Field guidance:
- ticket_id: the ticket's own unique identifier (e.g. "Jegy azonosító: 4087040").
- holder_name: the spectator / ticket holder name ("Név").
- event_name: the event/match as printed (e.g. "FTC - Panathinaikos FC").
- event_datetime: the event start, normalized to ISO 8601 (Hungarian "2026.01.22 21:00" → "2026-01-22T21:00").
- venue: the stadium / venue name (e.g. "FERENCVÁROS STADION").
- birth_place / birth_date: the holder's place and date of birth ("Születési hely" / "Születési idő"); birth_date as ISO YYYY-MM-DD.
- card_number: the supporter card number ("Kártyaszám") when present.
- gate: the entry gate / gate group ("Kapu/Gate", e.g. "III-as kapucsoport D1-D4 szektor").
- sector: the sector label ("Szektor/Sector", e.g. "D3 szektor").
- row / seat: the row ("Sor/Row") and seat ("Szék/Seat") within the sector, exactly as printed.
