"""Domain modules (180, plan 170 E7): what a domain adds to the shared code, in one place each.

Plain-language summary: the framework is general; what it knows about invoices, bank statements, utility bills or
emails comes from a domain. A domain module holds only registrations: the checks, the logic packs, the rules run after
an item, the parts of the downloads, each pointing at the code that does the work in its own module. The shared code
asks the registries and never names a domain. `registrations.load_all()` calls each domain's `register()` once per
process; importing a domain module registers nothing. 185: a domain module also names the modules of its addresses of
the local service (`SERVICE`), which `jav.api.service_modules` adds. 191: a domain module names the modules it is made
of (`MODULES`), and any number of domains can register.

- `jav/domains/finance.py`: invoices, statements, the reconciliation and the utility cost;
- `jav/domains/email.py`: emails and mailbox packages;
- `jav/domains/quotes.py` (191): quote requests and quotes.
"""

# the order `registrations.load_all` registers them in
DOMAINS = ("jav.domains.finance", "jav.domains.email", "jav.domains.quotes")
