
# Full architectural logic: 
**Data Sources, SEC Filtering, Conflict Weighting, Frequency, and Exit Logic.**


### Fundamentals and Technicals
Consider fundamentals and technicals for conviction score. Here is the factual market logic for why they are necessary and how to weigh them.

---

### Why Support & Resistance (S/R) Matter for Your Agent

Even if a "Whale" buys a massive amount of stock, if the price is currently sitting right at a major **multi-year resistance level**, the probability of a pullback is high. A conviction score that ignores this would be misleading.

#### 1. The "Whale Trap" Prevention

Institutional "Whales" often buy in blocks. If your agent sees a whale buy but the price is at resistance, that whale might be "gamma hedging" or selling covered calls rather than betting on an immediate breakout. Integrating S/R data helps the agent distinguish between **Aggressive Entry** and **Risk Management**.

#### 2. Self-Fulfilling Prophecies

Because millions of retail traders and algorithmic bots watch the same levels (like the 200-day Moving Average or horizontal support), the price often reacts at these levels regardless of the company's "true" fundamental value.

#### 3. Crowdsourced Sentiment Context

You are tracking Reddit and X. Social media hype usually peaks when a stock is "breaking out" of resistance. If your agent sees high social sentiment but the price is  above its support level, the conviction score should actually **decrease** because the trade is "extended" (overbought).

---

### How to Factor Them into a Conviction Score

A robust conviction score should be a **weighted average** of your different data inputs. Factually, market experts often split the weight based on the intended trade duration:

| Data Category | Component | Recommended Weight (Short-Term) | Recommended Weight (Long-Term) |
| --- | --- | --- | --- |
| **Whale Activity** | Options Flow / Dark Pools | 40% | 20% |
| **Social Sentiment** | X / Reddit Trends | 20% | 5% |
| **Technicals** | **Support / Resistance** | **30%** | **15%** |
| **Fundamentals** | Earnings / Insider Buys | 10% | 60% |

> **Factual Rule:** If the price is at **Support**, it acts as a "Multiplier" for your conviction score. If the price is at **Resistance**, it acts as a "Penalty" (divisor) for the score.

---

### Where to get this data for free?

* **Finviz API/Scraper:** Finviz automatically calculates support and resistance lines for almost every ticker.
* **Technical Indicator APIs:** Use the **Alpha Vantage** or **Yahoo Finance** APIs to pull the **SMA 50** and **SMA 200** (Simple Moving Averages). These act as "dynamic" support and resistance levels that are factually used by almost all institutional algorithms.


### Conviction Score
To create a factual, non-hallucinated **Conviction Score ( )**, we need to move away from "vibes" and into a weighted mathematical model. This score tells your agent whether a "Whale Buy" is a high-probability entry or a high-risk chase.

Here is the logic for a scoring engine that combines **Whale Flow**, **Social Sentiment**, and **Technical Levels**.

---

### 1. The Conviction Score Formula

We treat the Whale and Social data as the **Signal**, and the Support/Resistance (S/R) levels as the **Filter**.

CS = (Ww * Sw + Ws * Ss) * Ft

**Where:**

* Sw: Whale Signal (Volume and Aggression)
* Ss: Social Sentiment (X/Reddit Volume and Polarity)
* Ft: Technical Factor (Multiplier based on S/R proximity)
* Ww: Weights (Percentage of importance)
* Ws: Weights (Percentage of importance)

---

### 2. Fact-Based Input Scoring

To make this work, your agent needs to assign a value (0 to 10) to each data point it scrapes:

#### **A. Whale Signal (Sw)**

* **+10:** Multi-million dollar "Sweep" orders (aggressive buying at the ask price).
* **+5:** Large "Block" trades in Dark Pools.
* **-5:** Large Put buying (Whale is betting against the stock).

#### **B. Social Sentiment (Ss)**

* **+10:** Ticker mentions on Reddit/X are spiking  above the 7-day average with positive keywords ("long," "call," "breakout").
* **+2:** Steady chatter.
* **-10:** Mentions spike but keywords are negative ("crash," "rug pull," "halt").

#### **C. The Technical Multiplier (Ft)**

This is the most critical part. It acts as a "Safety Valve."

| Price Position | Multiplier (Ft) | Logic |
| --- | --- | --- |
| **At Support** | **1.5x** | High Reward/Risk. The "Whale" is buying at the floor. |
| **Between Levels** | **1.0x** | Neutral. No immediate technical barrier. |
| **At Resistance** | **0.5x** | Danger. Even with Whale buying, the price may bounce off the ceiling. |

---

### 3. Real-World Scenario

Let’s look at a factual example of how your agent would process a ticker like **NVDA**:

1. **Whale Feed:** Detects a $5M Call Option sweep. (Sw = 10)
2. **Social Feed:** Reddit mentions are average, no major spike. (Ss = 2)
3. **Technical Level:** The price is currently **2% below a major Resistance** level. (Ft = 0.5)

**Calculation (using 70/30 weighting):**

    (0.7 * 10 + 0.3 * 2) * 0.5 = 3.8 (Low Conviction)


**The Result:** Even though a Whale spent $5M, the agent gives a low score because the price is hitting a ceiling. It tells you to **wait for a breakout.**

---

### 4. Implementation Steps

To build this, you need to set up three "Listeners" in your agent:

* **The Auditor:** Watches SEC Form 4 and Options APIs for Whale activity.
* **The Listener:** Scrapes Reddit/X for "Cashtag" frequency.
* **The Mapmaker:** Pulls the 50-day and 200-day Moving Averages to identify the "Floor" and "Ceiling."


### SEC Form 4 Transaction Codes Logic for Gifts vs Open Market Purchases

Here is the factual breakdown of the SEC codes you need to program into your agent's logic.

---

### 1. The "Golden" Code: **P (Open Market Purchase)**

This is the only code that should significantly boost your Conviction Score.

* **What it is:** An insider (CEO, CFO, Director) used their **own personal cash** to buy shares at the current market price.
* **Why it matters:** Peter Lynch famously said, "Insiders might sell their shares for any number of reasons, but they buy them for only one: they think the price will rise." This is "skin in the game."
* **Agent Logic:** If Code = **P**, increase  (Whale Signal) by **+10**.

### 2. The "Neutral" Code: **A (Grant/Award) or M (Exercise)**

* **What it is:** The company gave the insider stock as part of their salary (A) or the insider exercised options they already owned (M).
* **Why it matters:** This doesn't show market conviction; it shows the insider is getting paid. They aren't spending "new" money.
* **Agent Logic:** If Code = **A** or **M**, the signal is **Neutral (+0)**.

### 3. The "Noise" Code: **G (Gift)**

* **What it is:** A "Bona Fide Gift" of securities to or from the insider (often to a family trust, charity, or relative).
* **Why it matters:** This is usually done for tax planning or estate management. It has zero correlation with the insider’s view on the stock's future price.
* **Agent Logic:** If Code = **G**, ignore the transaction entirely (**Ignore**).

---

### SEC Form 4 Cheat Sheet for Your Agent

When your agent scrapes the SEC EDGAR API (which is free), it will look for a table. You need to map these specific codes to your scoring engine:

| SEC Code | Transaction Type | Conviction Level | Action for Agent |
| --- | --- | --- | --- |
| **P** | **Open Market Purchase** | **Highest** | **Triggers Alert / High Score** |
| **S** | Open Market Sale | Low/Medium | Decrease Score (Potential Red Flag) |
| **A** | Grant / Award | Low | Ignore (Compensation) |
| **M** | Exercise of Options | Low | Ignore (Administrative) |
| **G** | **Bona Fide Gift** | **None** | **Strictly Filter Out** |

### Pro Tip: The "Cluster Buy" Multiplier

If your agent detects **three or more different insiders** all using Code **P** within the same 5-day window, this is called a **Cluster Buy**. This is one of the most statistically significant bullish signals in the market.


### 10b5-1 Trading Plans

To avoid "fake signals," your agent must understand **Rule 10b5-1 Trading Plans**. These are the most common reason for "false positives" in insider trading data.

### 1. What is a 10b5-1 Plan?

A 10b5-1 plan is a **pre-scheduled** agreement where an insider says, *"Sell 5,000 shares on the 15th of every month for the next year."* Because the trade was planned months ago, it is **not** a reaction to current market trends or "secret" news. If your agent treats a 10b5-1 sale as a "Whale selling before a crash," it is hallucinating a signal that isn't there.

---

### 2. How Your Agent Detects the "Fake" Signal

Fortunately, the SEC requires insiders to check a box on **Form 4** if the trade was part of a 10b5-1 plan.

| Transaction Type | 10b5-1 Checkbox | Conviction Score Impact |
| --- | --- | --- |
| **Discretionary Buy** | **No** | **+10 (Highest)** – Insider decided to buy *now* with their own cash. |
| **Discretionary Sale** | **No** | **-5 (High)** – Insider decided to exit *now*. |
| **10b5-1 Purchase** | **Yes** | **+2 (Low)** – Scheduled long ago; doesn't reflect current sentiment. |
| **10b5-1 Sale** | **Yes** | **0 (Neutral)** – Usually just an executive paying for a house or taxes. |

### 3. The "Cooling-Off" Rule (Fact Check)

As of 2023/2024 SEC updates, insiders have a **"Cooling-Off Period"** of at least **90 days** (or 2 days after the next earnings report) between setting up a plan and making the first trade.

* **Why this matters for your agent:** If a trade happens under a 10b5-1 plan, you know for a fact the insider made that decision at least 3 months ago. It is "stale" data for a real-time advisor.

### 4. When a 10b5-1 Plan IS a Real Signal

There is one exception: **Plan Adoptions.**
If your agent scrapes a company's **10-Q (Quarterly Report)** or **10-K (Annual Report)** and sees that 5 different executives just *adopted* new 10b5-1 plans to **Buy**, that is a massive future signal.

* **The Logic:** They are collectively signaling that they want to buy as much as possible over the next year, starting after the cooling-off period.

---

### Summary of Agent Logic

To make your agent truly "intelligent" and factual, program these filters:

1. **Filter Out:** Any transaction where the 10b5-1 checkbox is marked "Yes" (unless you are doing long-term trend analysis).
2. **Highlight:** "Open Market Purchases" (Code P) where the 10b5-1 box is "No."
3. **Cross-Reference:** If an insider buys (Code P) and Reddit/X sentiment is also spiking, the **Conviction Score** should hit its maximum.

### Divergence Logic

When your data sources disagree—for example, a **Whale** is aggressively buying but **Reddit** is in a state of panic—this is called **Divergence**.

Factually, in institutional trading, a divergence is often a more powerful signal than when everything aligns, because it reveals where the "Smart Money" is taking the opposite side of a "Crowded Retail Trade."

---

### 1. The Conflict Weighting Logic

To handle this, your agent needs a **Hierarchy of Truth**. In the business of market data, not all signals are created equal.

| If This Happens... | Market Reality | Agent Decision | Conviction Adjustment |
| --- | --- | --- | --- |
| **Whale Buys / Social Panics** | **Accumulation.** Institutional investors are "buying the dip" while retail is being shaken out. | **Bullish Divergence** | **Increase Score (+5)** |
| **Whale Sells / Social Hypes** | **Distribution.** Institutions are using retail "FOMO" as liquidity to exit their positions. | **Bearish Divergence** | **Decrease Score (-10)** |
| **Whale Buys / Social Hypes** | **Momentum.** Everyone is aligned. High risk of being a "top" but strong short-term trend. | **Alignment** | **Steady Score** |

### 2. Why the "Whale" Always Wins the Tie

If you are building an intelligent advisor, you must weight the **Whale Flow ()** significantly higher than **Social Sentiment ()**.

* **Whales** move the market with **Capital**.
* **Social Media** moves the market with **Noise**.

**Factual Rule:** If the Whale and Social signals conflict, the agent should default to the Whale's direction but lower the *size* of the conviction.

**Updated Formula for Conflict:**
If  and  have opposite signs (+/-):

if Sw and Ss have opposite signs (+/-):
    CS = (Sw * 0.8) + (Ss * 0.2)

*This ensures the "Smart Money" carries 80% of the weight during a disagreement.*

---

### 3. Detecting "Liquidity Traps"

The most dangerous scenario for your agent to catch is when Social Media sentiment is **Extreme Bullish** (e.g., "To the moon!" posts on Reddit) while the Whale data shows **Dark Pool Selling**.

This is factually known as **Institutional Distribution**. The big players need someone to buy the shares they are selling; they use the retail hype to ensure there are enough buyers so they can exit without crashing the price immediately.

> **Agent Alert:** If `Social_Sentiment > 8` AND `Whale_Flow < 2`, trigger a **"Liquidity Trap"** warning.

---

### 4. The "Final Filter" Table

Before the agent outputs a final recommendation, it should pass the score through this logic gate:

| Whale Signal | Social Signal | Technical Level | Final Conviction Output |
| --- | --- | --- | --- |
| Buy | Panic | At Support | **Ultra-High** (The "Value" Play) |
| Buy | Hype | At Resistance | **Low** (The "Chase" Warning) |
| Sell | Hype | At Resistance | **Critical Sell** (The "Rug Pull" Risk) |
| Sell | Panic | At Support | **Neutral** (The "Bottoming" Phase) |

### Data refreshing frequency

To keep your conviction score accurate, the agent needs to update different data sources at different speeds. Refreshing everything every second is a waste of resources, while refreshing once a day makes the agent useless for "Whale" tracking.

Here is the factual **Frequency Map** for your agent's data pipeline:

---

### 1. Data Refresh Hierarchy

| Data Source | Type | Recommended Frequency | Market Reality |
| --- | --- | --- | --- |
| **Price Data** | Quantitative | **Every 1–5 Seconds** | Essential for calculating if the stock is at Support/Resistance *right now*. |
| **Social Sentiment** | Unstructured | **Every 5–15 Minutes** | Social trends (Reddit/X) move in "waves." Checking every second is mostly noise; 15 mins captures the "momentum." |
| **Whale Options** | Flow | **Every 1 Minute** | "Sweeps" and "Blocks" are time-sensitive. You want to see these as close to the tape as possible. |
| **SEC Filings** | Regulatory | **Every 10 Minutes** | The SEC EDGAR RSS feed updates every 10 minutes (Mon–Fri, 6 AM – 10 PM EST). Polling faster is usually unnecessary. |
| **Fundamentals** | Corporate | **Once Daily** | Earnings dates and debt ratios don't change intraday. |

---

### 2. Strategic Implementation for the Agent

#### **The "Event-Driven" Trigger**

Instead of just polling on a timer, your agent should use **Conditional Logic**.

* **Scenario:** If the **Whale Flow** detects a massive buy, the agent should immediately "Force Refresh" the **Social Sentiment** and **Price Levels** to see if a breakout is happening in that exact moment.

#### **Social Media "Cooldown" Logic**

Social media is prone to "bot spikes." To keep your Conviction Score factual:

* **Rule:** Require the "Sentiment Spike" to persist for at least **two refresh cycles** (e.g., two 15-minute windows) before it fully boosts the score. This prevents your agent from reacting to a single viral (but fake) post.

---

### 3. Avoiding "Rate Limits" (The Business Constraint)

Since you want to avoid high costs, you must manage how many "calls" your agent makes to these APIs:

* **SEC EDGAR:** It is a free government service, but they will block your IP if you poll more than **10 times per second**. A 10-minute heartbeat is the "industry safe" standard for free tools.
* **Reddit/X:** Use "streaming" endpoints if available, which push data to you only when your specific keywords (tickers) are mentioned. This is more efficient than "scraping" the whole site.

### Summary Checklist for your Agent's "Heartbeat":

1. **Fast Lane (1-60s):** Prices, Options Flow.
2. **Medium Lane (10-15m):** Reddit, X, SEC Form 4s.
3. **Slow Lane (24h):** Support/Resistance levels (unless the price moves ), Earnings Calendars.



### Exit Strategy

To determine when the "Whale Move" is over, your agent needs an **Exit Logic** that is just as cold and factual as the entry logic. Most retail investors fail because they enter with the Whale but don't leave when the Whale does.

An intelligent agent must monitor for **"Signal Decay"**—the point where the original reason for the trade no longer exists.

---

### 1. The Three "Exit Triggers"

Your agent should monitor these three specific factual shifts to generate an Exit Signal:

#### **A. The Hedge/Flip (Whale Exit)**

* **The Signal:** The agent detects the same "Whale" (or similar large volume) buying **Opposing Put Options** or an **Insider Sale (Code S)**.
* **The Logic:** If the Whale who triggered the entry starts "hedging" (protecting their position), the conviction score for a long trade should drop to **zero**.
* **Factual Check:** Look for "Sell to Close" orders in the options flow, which indicate the Whale is taking their money off the table.

#### **B. The Social "Blow-Off Top"**

* **The Signal:** Social sentiment (Reddit/X) hits an all-time high (Extreme Euphoria), but the **Price Action** stops going up.
* **The Logic:** This is a factual indicator that the "last buyer" has entered. When everyone on Reddit is already "in," there is no one left to push the price higher.
* **Agent Action:** Trigger a "Trailing Stop-Loss" alert.

#### **C. Technical Resistance Failure**

* **The Signal:** The price hits the **Resistance Level** we identified earlier and "wicks" (touches and immediately drops) on high volume.
* **The Logic:** If the "Whale" buy couldn't break the ceiling, the ceiling is stronger than the Whale.

---

### 2. The "Exit Conviction" Table

Just like the entry, the exit should be weighted.

| Exit Indicator | Weight | Meaning |
| --- | --- | --- |
| **Price hits Resistance** | 30% | The technical goal is reached. |
| **Whale buys Put options** | 50% | The Smart Money is betting on a drop or protecting gains. |
| **Social Sentiment > 90/100** | 20% | The trade is "crowded" and likely near a peak. |

---

### 3. Calculating the "Profit Protection" Score

Your agent should calculate a **Risk-to-Reward Decay**.

Decay = (Current Price - Entry Price) / (Resistance Price - Entry Price)


* If **Decay = 0.9 (90%)**: The stock has traveled 90% of the way to the target. The agent should recommend tightening the stop-loss to **1%** below the current price.
* If **Decay > 1.0**: The stock broke resistance. The agent resets the "Map" and looks for the *next* resistance level.

---

### 4. Summary of Agent Output

At the end of each refresh cycle, your agent's dashboard should look like this (Factual & Market-focused):

> **Ticker:** $XYZ
> **Conviction Score:** 8.4/10 (High)
> **Primary Driver:** Cluster Buy (3 Insiders, Code P) + Reddit Sentiment Spike (+200%).
> **Technical State:** 4% above Support ($150), 12% below Resistance ($180).
> **Risk Alert:** 10b5-1 Plan detected for CEO in 30 days; monitor for "Exit Decay."




