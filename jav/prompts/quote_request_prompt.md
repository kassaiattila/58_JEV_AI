You read a customer's request for a price quote (árajánlatkérés, ajánlatkérés) sent to a company that sells goods and services. The source text is the request itself: an email (its From, Date and Subject lines first, then the sender's own text without the quoted earlier messages), or a request form or list (a PDF, or a table whose rows are the lines, its cells three spaces apart).

Extract these fields; leave a field null when the request does not state it:

- `customer_name`: the organisation that asks for the quote, as it names itself (in the signature, the letterhead or the form's "Ajánlatkérő" / "Customer" field), with its legal form (Kft., Bt., Zrt., Ltd). When a private person asks without an organisation, the person's name. Never the company the request is addressed to.
- `customer_tax_number`: the customer's tax number (adószám, VAT number), as printed.
- `contact_name`: the person who asks, or who is named as the contact (kapcsolattartó).
- `contact_email`: the contact's email address: the one printed as the contact's, otherwise the sender's address on the From line.
- `contact_phone`: the contact's phone number, as printed.
- `deadline`: the date by which the customer wants the quote, as an ISO date (YYYY-MM-DD). When the request gives it relative to its own date ("két héten belül", "by next Friday"), count it from the email's Date line or the form's own date. Not a delivery, installation or meeting date. Null when no deadline for the quote is given.
- `reference`: the customer's own reference for this request (a tender, project, purchase request or RFQ number), as printed; not a phone or tax number.
- `requested_items`: every item the customer asks a price for, in the order written, one row each:
  - `description`: the item as the request writes it (without its quantity);
  - `quantity`: how many, as a number; a quantity written in words counts ("három darab" = 3, "two" = 2), and when a duration is given in days and in hours too, the hours;
  - `unit`: the unit as the request gives it (db, szett, óra, alkalom, felhasználó, pcs, users), or null when none is given.
  Only items the customer asks for now: not the items of a quoted earlier message, not what was already delivered, and not an offer's own example items.
