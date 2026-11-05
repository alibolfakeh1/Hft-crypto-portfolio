"""Event-driven research simulator for the `V0` variant, in `IDEAL-1M` mode.

It sends nothing to any venue. Every fill here is a line of arithmetic on stored bars.

Layers, as in charter section 2:
- `tape` and `market` release closed bars and trades only when their time has come.
- `strategies` propose setups and manage positions, and see nothing else.
- `fills` is the order layer: collar, entry fill, size.
- `exits` is the exit layer: the C8 ratchet.
- `simulator` walks 1m bars under C7 and calls the others in time order.
- `portfolio` applies the gross exposure cap across streams.
- `accounting` books every cash flow in whole cents, so trades and equity reconcile exactly.
"""
