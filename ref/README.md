# Developer notes

Notes for people working on CJTrade itself: design records, investigations,
test plans and the to-do list. Nothing here is user documentation, and much
of it describes the code as it was when it was written. User documentation
lives in `doc/` and is published at https://jackiesogi.github.io/CJTrade/.

| File | What it is |
|---|---|
| `TOOLS.md` | Every entry point (commands, scripts, servers, dev workflow) and how to run it, with known problems (Chinese) |
| `TODO.md` | Open work items |
| `CALLBACK.md` | Design notes for the order-fill callback |
| `CALLBACK_TEST_PLAN.md` | How the Sinopac callback paths were tested with real odd-lot orders |
| `ONESHOT_VS_FULLSIM_ANALYSIS.md` | Why `oneshot` and `full_sim` backtests disagree (Chinese) |
| `order_lifecycle.md` | Mermaid source of `doc/assets/img/order_lifecycle.png` |
| `arenax_legacy_backend_checklist.md` | Checklist from the legacy ArenaX backend |
| `arenax/` | ArenaX notes: backend architecture, an avg-cost investigation |
| `public_listed.csv` | TWSE listed-company data used during development |
| `weird_order_states_arenax.log` | A captured log of odd ArenaX order states |
