<!-- 197 (plan 197 K2): made from configs/type_drafts/belepo_jegy_taught.json by jav/type_teaching.py; edit the draft, not this file. -->
You read an admission ticket to an event (a match or a concert) with the event, its time and place, the ticket holder and the holder's seat. The source text is the document itself, one line per printed line.

Extract these fields; leave a field null when the document does not state it:

- `ticket_id`: the ticket's own identifier, the number printed as its id (azonosító).
- `holder_name`: the name of the person the ticket is issued to (név).
- `event_name`: the event the ticket admits to, as printed: the match's two teams with the dash between them, or the concert's title (mérkőzés, meccs, párharc, párosítás).
- `event_datetime`: the event's date and starting time, written as YYYY-MM-DDTHH:MM (időpont, dátum és idő).
- `venue`: the name of the stadium, arena or hall where the event is held, as printed (helyszín); not its address.
- `birth_place`: the ticket holder's place of birth (születési hely).
- `birth_date`: the ticket holder's date of birth (születési idő). Write it as an ISO date (YYYY-MM-DD).
- `card_number`: the number of the holder's club or fan card printed on the ticket (kártyaszám).
- `gate`: the entrance gate exactly as printed in the ticket's gate field (Kapu/Gate), with every word and gate number of that field, not only its first part.
- `sector`: the sector as printed in the ticket's sector field (Szektor/Sector), with its mark and the word that follows the mark.
- `row`: the row number within the sector (Sor/Row).
- `seat`: the seat number within the row (Szék/Seat).

Copy each value as it is printed, unless its description says how to write it.
