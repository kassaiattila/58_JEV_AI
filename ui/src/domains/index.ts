// 231 (plan stage C, C3e; DECISIONS 231): the domains of the interface, as the service's (`jav/domains/__init__.py`
// `DOMAINS`). Each registers its screens with the shared registries when the interface loads (`ui/src/main.tsx`; the
// tests' setup too), so the shared code names no domain's screen: the strict principle's test checks that nothing
// outside `ui/src/domains/` imports a domain's module but the interface's start, and that no domain imports another.
import "./email";
