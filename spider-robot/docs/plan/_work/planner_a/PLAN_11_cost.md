# 11. Cost

Prices checked 2026-11-09/10. Most come from third-party trackers, because I could not open the
vendors' own pricing pages. Confirm before relying on them.

## 11.1 Unit prices

| Item | Price | Source, date | Confidence |
|---|---|---|---|
| Claude Opus 5.5 | $4 / $20 per Mtok in / out; $0.20 cached read | finout.io, layer3labs.io, 2026 | Several trackers agree; official page not opened |
| Claude Haiku 5.5, under 100k-token prompts | $0.10 / $0.50 per Mtok | mixed-news.com, braindetox.kr, 2026 | Trackers |
| Gemini 2.5 Flash | $0.30 / $2.50 per Mtok; audio input $1 per Mtok | openrouter.ai, developer.puter.com, 2026 | Trackers |
| Gemini 2.5 Flash Preview TTS | $0.50 / $10 per Mtok | metacto.com | One secondary source |
| NVIDIA NIM `moonshotai/kimi-k3` | "Free Endpoint", trial terms, no published price | build.nvidia.com, 2026-11-09 | Vendor page, via search |
| NVIDIA NIM `kimi-k3.1-pro` | **No API yet**: "API access for this model is not available yet", updated 2026-11-04 | build.nvidia.com model page, fetched 2026-11-09 | Vendor page |
| Tailscale Personal | Free, non-commercial, 6 users | tailscale.com docs, validated 2026-04-08 | Vendor |
| Telegram Bot API | Free | n/a | |
| EC2 c7i.4xlarge, Tokyo | $0.8988 per hour | doit.com, 2026 | Aggregator |
| EC2 m7i.2xlarge, Tokyo | $0.5208 per hour | doit.com, 2026 | Aggregator |
| EC2 c7i.4xlarge, us-east-1 | $0.714 per hour | holori.com, doit.com, 2026 | Aggregator |
| EBS gp3 | $0.08 per GB-month, US regions | aws.amazon.com/ebs, 2026 | Vendor. **Tokyo not found; assume $0.096 [A]** |
| Electricity | $0.25 per kWh | **[A]** Replace with your tariff | |

Sources: [finout](https://www.finout.io/blog/claude-opus-5.5-pricing-2026-what-anthropics-new-flagship-actually-costs),
[layer3labs](https://www.layer3labs.io/guides/claude-opus-5-5-api-pricing),
[mixed-news](https://mixed-news.com/en/?p=35955),
[braindetox](https://braindetox.kr/en/posts/claude_haiku_5_5_release_pricing_2026.html),
[OpenRouter](https://openrouter.ai/blog/gemini-25-flash-api-pricing-quickstart-provider-comparison),
[Puter](https://developer.puter.com/tutorials/gemini-api-pricing/),
[metacto](https://metacto.com/blogs/the-true-cost-of-google-gemini-a-guide-to-api-pricing-and-integration),
[NVIDIA kimi-k3](https://build.nvidia.com/moonshotai/kimi-k3),
[NVIDIA kimi-k3.1-pro](https://build.nvidia.com/moonshotai/kimi-k3_1-pro.md),
[Tailscale](https://tailscale.com/docs/account/manage-plans/free-plans-discounts.md),
[DoiT c7i Tokyo](https://www.doit.com/compute/spot/ap-northeast-1/c7i.xlarge),
[DoiT m7i Tokyo](https://www.doit.com/compute/spot/ap-northeast-1/m7i.xlarge),
[Holori us-east-1](https://calculator.holori.com/aws/ec2/c7i.4xlarge/us-east-1),
[AWS EBS](https://aws.amazon.com/ebs/general-purpose).

## 11.2 Monthly scenarios

All usage figures are **[A]**; change them to match real use.

### Home only: no cloud calls

| Item | Calculation | USD per month |
|---|---|---|
| Server, 60 W, 24/7 **[E]** | 43 kWh. The server is already on for daily use, so the true extra cost is lower | up to 10.80 |
| Pi and L2, 15 W for 2 h a day **[E]** | 0.9 kWh | 0.23 |
| Servo charging, 30 Wh a day **[E]** | 0.9 kWh | 0.23 |
| Tailscale, Telegram | Free | 0 |
| **Total** | | **about 0-11** |

### Typical: some cloud

| Item | Calculation | USD |
|---|---|---|
| Home power | As above | 0-11 |
| Telegram chats on Haiku | 600 a month × (3k in + 300 out) | 0.27 |
| Multi-step tasks on Opus | 60 a month × (48k in, 90% cached, + 4k out). Each ≈ $0.12. `max_task_usd` caps a task at $1 | 7.20 |
| Gemini voice notes in, TTS out | 10 a day × 15 s, and short replies | under 0.20 |
| Kimi via NIM | Free endpoint, if it stays free **[A]** | 0 |
| **Total** | | **about 8-19** |

### Heavy: regular AWS mapping

| Item | Calculation | USD |
|---|---|---|
| Typical, above | | 8-19 |
| Worker, c7i.4xlarge Tokyo | 40 h a month × $0.8988 | 35.95 |
| Disk, 200 GB gp3, always billed | 200 × $0.096 **[A]** | 19.20 |
| Data out | Only finished maps return; small | under 1 |
| **Total** | | **about 64-75** |

A stopped instance still bills its disk (agreed architecture). A smaller 100 GB disk saves about $9.60.
Point-LIO runs from a recording, so the home server can do small maps for free, at the cost of pausing
vision during the job.

**Required before first use:** `infra/aws/worker/budget_alarm.sh`, default $20 with an alert at 80%.
Set a higher limit deliberately if you choose heavy use.

## 11.3 One-time hardware to add

| Item | Estimate **[E]** |
|---|---|
| E-stop switch, relay or contactor, fuse, timer board, low-voltage buzzer | $25-45 |
| Pi 4 heatsink and fan, if not fitted | $5-15 |
| LiDAR mast or bracket | $5-20 |
| Optional later: GPU machine | Not costed; the plan works without one |
