## Crypto gain sources scan

Date: 2026-05-24

### Best current targets for AI-assisted discovery and claim tracking

1. Zealy
- Official docs say quests can be automated or manually approved.
- Zealy added USDC rewards on 2025-09-17 and says USDC is distributed directly to connected wallets upon quest completion.
- Daily Challenge offers Zaps for completing 3 quests, with payouts after the daily lottery.
- Good fit for automation:
  - quest discovery
  - filtering for auto-validated quests
  - reward tracking
- Limits:
  - wallet/account still needed
  - actual participation may still require human-linked social accounts

2. Galxe
- Official docs expose APIs for quest validation, eligibility checks, reward tracking, and quest status.
- Good fit for automation:
  - scanning active quests
  - checking eligibility against wallet addresses
  - tracking reward/claim status
- Limits:
  - API access token required from dashboard
  - many quests still depend on wallet signatures or off-platform actions

3. TaskOn
- Official docs say participation is free and generally no KYC is required.
- Rewards can be distributed by TaskOn or the creator; TaskOn-distributed rewards are usually sent within one week.
- Good fit for automation:
  - campaign discovery
  - filtering for TaskOn-distributed rewards
  - monitoring Participant Center / winner flow
- Limits:
  - some claims are winner-based, not guaranteed
  - some tasks depend on bound social accounts

4. Layer3
- Current discover page says users can complete actions and get tokens instantly in wallet with Liquid Rewards.
- Good fit for automation:
  - discovery
  - reward-rate tracking
  - task classification
- Limits:
  - terms prohibit access through bots/scripts
  - wallet interactions remain user-responsibility

5. Superteam Earn
- Current official listings page shows active bounty/project opportunities paying USDC, SOL, and other tokens.
- Good fit for AI assistance:
  - drafting submissions
  - bounty triage
  - filtering by due date, prize pool, skill, and geography
- Limits:
  - competitive, not guaranteed
  - payout only after sponsor review / winner selection

### Notable "do not automate participation" flags

1. Layer3 terms prohibit access through automated or non-human means.
2. QuestN terms prohibit access through automated or non-human means.
3. Base Creator Rewards rules prohibit use of any automated system to participate.

### Dead / lower-priority leads

1. Coinbase Learning Rewards
- Official help page says Learning Rewards ended on 2025-05-27.
- Not worth building automation around.

### What to do next

1. Build around Zealy, Galxe, and TaskOn first.
2. Treat Layer3 and QuestN as browse-only unless the user explicitly wants manual participation.
3. Pull wallet addresses from `claims_export` column B downward if/when accessible locally.
4. Create a normalized table:
- platform
- reward type
- auto distribution
- manual review
- wallet needed
- anti-bot risk
- current lead URL
- notes
