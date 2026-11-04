# HFT Crypto Portfolio

Research into mid-frequency strategies on BTC and ETH. Advanced candle strategies propose trades, then
order-flow and order-imbalance features help decide whether and when to enter and when to exit. Each strategy
has a dynamic stop and target model. Results are shown as a professional portfolio, and live paper positions
will be published to a Telegram channel.

> **Status: documents only.** No code has been written and no strategy has been tested. There are no results.

> **Not investment advice.** Backtests are labelled `SIMULATED` and forward results are labelled `PAPER`. This
> project sends no real orders.

<div dir="rtl">

## خلاصه

این پروژه پژوهشی روی استراتژی‌های میان‌فرکانس بیت‌کوین و اتریوم است. استراتژی‌های پیشرفتهٔ کندلی مثل پیوت و عرضه و تقاضا پیشنهاد معامله می‌دهند. بعد فیچرهای جریان سفارش و عدم‌تعادل سفارش کمک می‌کنند تصمیم گرفته شود که آیا و چه زمانی وارد شویم و چه زمانی خارج شویم. حد سود و حد ضرر هر استراتژی داینامیک است و خروجی‌ها به‌صورت پرتفوی نمایش داده می‌شوند. پوزیشن‌های زندهٔ کاغذی هم در کانال تلگرام منتشر خواهند شد.

**وضعیت فعلی:** فقط مستندات وجود دارد. هنوز کدی نوشته نشده و هیچ استراتژی‌ای تست نشده است، پس نتیجه‌ای هم در کار نیست.

**این پروژه توصیهٔ سرمایه‌گذاری نیست و سفارش واقعی ارسال نمی‌کند.**

</div>

## How a trade is decided

```text
closed candles -> Setup -> Flow entry gate -> Simulated order -> Dynamic stop and target, flow exit -> Portfolio
                           ENTER WAIT VETO                       HOLD TIGHTEN SCALE_OUT EXIT
```

Every strategy runs with and without flow, so the value of each decision can be measured instead of assumed.

| Variant | Entry | Exit |
|---|---|---|
| `V0S` | Candle only | Fixed stop and target, as a control |
| `V0` | Candle only | Dynamic stop and target |
| `VE` | Flow gate | Dynamic stop and target |
| `VX` | Candle only | Dynamic stop and target, plus flow |
| `VEX` | Flow gate | Dynamic stop and target, plus flow |

## Documents

| Document | Contents |
|---|---|
| [Charter](docs/00_CHARTER.md) | Scope, decision stack, timing contract, data tiers, gates, dynamic stops, live positions |
| [Strategies](docs/01_strategies/) | The candle strategies and their dynamic stop and target models |
| [Feature usage](docs/02_features/) | Which flow features are used at which decision point |
| [Leak reviews](docs/reviews/leak/) | Independent future-leak audits |
| [Portfolio outputs](docs/04_PORTFOLIO_OUTPUTS.md) | All metrics, charts and reports |
| [Data lifecycle](docs/05_DATA_LIFECYCLE.md) | Storage, retention, deletion and disk limits |
| [App and UI](docs/06_APP_AND_UI.md) | Desktop app and Telegram channel |
| [Roadmap](docs/07_ROADMAP.md) | Phases and current status |
| [Decision log](docs/decisions/DECISION_LOG.md) | Decisions made and decisions waiting |

## Team

Nine specialist agents, defined in [`.claude/agents/`](.claude/agents/). Writers never approve their own work.

| Agent | Responsibility |
|---|---|
| `project-manager` | Roadmap, gates, decisions, status |
| `strategy-architect` | Candle strategies and dynamic stop and target models |
| `feature-integrator` | Where flow features are used |
| `leak-auditor` | Future-leak audits |
| `python-reviewer` | Code correctness |
| `developer` | Production code and tests |
| `data-steward` | Data storage, retention and disk limits |
| `app-builder` | Telegram bot and desktop app |
| `ui-designer` | Visual design and report layout |
