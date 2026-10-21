# Market Risk Monitor

Market risk monitoring of a fictional multi-asset trading book in euros (equities, gold, euro rates, USD).

The goal: a nightly Python pipeline that collects and checks market data, forecasts volatility, computes a 99% VaR and a 97.5% Expected Shortfall, and backtests them, with the results reported in Power BI.

**Status:** work in progress. This README grows as each part is built.

## License

MIT, see [LICENSE](LICENSE).

## Credits

Built with help from [Claude Code](https://claude.com/claude-code) for the plumbing (ingestion, Docker, CI). The risk core (returns, volatility models, VaR, ES, backtests) is written by hand.
