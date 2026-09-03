"""Windows-only manual smoke check: confirms MT5 + the demo terminal are
reachable BEFORE trying to run the bridge itself.

Run on the Windows VM, with MetaTrader5 installed and already logged
into a DEMO account:

    python -m mt5_bridge.smoke

Does exactly:
    import MetaTrader5
    initialize()
    terminal_info()
    account_info()
    EURUSD symbol_info()
    EURUSD symbol_info_tick()
    shutdown()

Deliberately does NOT call `order_send` or anything else that could
place, modify, or close a position -- this script exists purely to
confirm the VM/terminal/account are reachable before anything else is
attempted. It prints only values that are safe to see on screen: no
password, no token, and no full filesystem paths.
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("ERROR: the MetaTrader5 package is not installed in this Python environment.")
        print("Install it with: pip install -r mt5_bridge\\requirements-windows.txt")
        return 1

    if not mt5.initialize():
        print(f"ERROR: MetaTrader5.initialize() failed: {mt5.last_error()}")
        return 1

    try:
        terminal = mt5.terminal_info()
        if terminal is None:
            print("ERROR: terminal_info() returned None -- is the MT5 terminal running?")
            return 1
        print("Terminal:")
        print(f"  connected      = {terminal.connected}")
        print(f"  trade_allowed  = {terminal.trade_allowed}")
        print(f"  name           = {terminal.name}")
        print(f"  company        = {terminal.company}")
        print(f"  build          = {terminal.build}")

        account = mt5.account_info()
        if account is None:
            print("ERROR: account_info() returned None -- is a terminal session logged in?")
            return 1
        trade_mode_names = {0: "DEMO", 1: "CONTEST", 2: "LIVE"}
        print("Account:")
        print(f"  login          = {account.login}")
        print(f"  trade_mode     = {trade_mode_names.get(account.trade_mode, f'UNKNOWN({account.trade_mode})')}")
        print(f"  server         = {account.server}")
        print(f"  currency       = {account.currency}")
        print(f"  balance        = {account.balance}")
        print(f"  equity         = {account.equity}")

        if account.trade_mode != 0:
            print()
            print("WARNING: this account does NOT report as DEMO. Do not proceed with")
            print("bridge testing against this account until that is resolved.")

        symbol = "EURUSD"
        info = mt5.symbol_info(symbol)
        if info is None:
            print(f"WARNING: symbol_info({symbol!r}) returned None -- symbol may not exist for this broker.")
        else:
            print(f"Symbol {symbol}:")
            print(f"  digits         = {info.digits}")
            print(f"  volume_min     = {info.volume_min}")
            print(f"  volume_step    = {info.volume_step}")
            print(f"  volume_max     = {info.volume_max}")
            print(f"  visible        = {info.visible}")

            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                print(f"WARNING: symbol_info_tick({symbol!r}) returned None -- no live tick yet.")
            else:
                print(f"  bid            = {tick.bid}")
                print(f"  ask            = {tick.ask}")

        print()
        print("Smoke check complete. No orders were placed.")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
