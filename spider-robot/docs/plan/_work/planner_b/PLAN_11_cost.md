# 11. Cost

Monthly, USD, prices read 2026-11-09 and 2026-11-10. Third-party aggregators are marked. Token and hour volumes are **assumptions [A]**: change them and the totals follow.

## Unit prices

| Item | Price | Source |
|---|---|---|
| Claude Opus 5.5 | $4 input, $20 output per MTok; cache read $0.20 | [claude.com/pricing](https://claude.com/pricing) |
| Claude Haiku 5.5 (≤100K) | $0.10 input, $0.50 output per MTok | Same |
| Gemini 2.5 Flash audio input | about $1.00 per MTok, secondary sources disagree | [Aggregator](https://www.morphllm.com/gemini-api-pricing); confirm with Google |
| NVIDIA NIM trial | Free, about 40 requests/min; not a production tier and no SLA | [NVIDIA forum](https://forums.developer.nvidia.com/t/request-to-increase-nvidia-nim-api-rate-limit-from-40-rpm-to-250-300-rpm/372594) |
| Tailscale Personal | Free, non-commercial | [Tailscale](https://tailscale.com/docs/account/manage-plans/free-plans-discounts.md) |
| Telegram Bot API | Free | Long-standing; not re-checked |
| Electricity, Japan residential | about ¥36/kWh, $0.229/kWh; date of figure unknown | [GlobalPetrolPrices](https://www.globalpetrolprices.com/Japan/electricity_prices/) |
| Home server draw | 30-60 W idle [E], varies by build | [Review roundup](https://www.kitguru.net/components/leo-waldock/intel-core-i7-8700k-and-core-i5-8400-with-z370-aorus-gaming-7/6); measure with a wall meter |
| EC2 c7i.2xlarge | $0.4494/h Tokyo; $0.357/h us-east-1 | [Holori](https://calculator.holori.com/aws/ec2/c7i.2xlarge/ap-northeast-1) (aggregator), [Economize](https://www.economize.cloud/resources/aws/pricing/ec2/c7i.2xlarge/) (aggregator) |
| EBS gp3 | $0.08/GB-month us-east-1; Tokyo about 10% higher [E] | [AWS](https://aws.amazon.com/ebs/pricing) plus aggregators |
| AWS Budgets | First two action-enabled budgets free | [AWS](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing) |
| Data out of AWS | $0.09/GB beyond the free allowance, third-party figure | Not re-checked at AWS |

## Scenarios

The home server's electricity is partly a cost the owner already pays. The increment from models is small; the column below counts the whole machine, which overstates this project's share.

| Line | Home-only | Typical | Heavy AWS |
|---|---|---|---|
| Server electricity, 45 W average, 730 h | $7.50 | $7.50 | $7.50 |
| Pi and robot electricity | under $1 | under $1 | under $1 |
| Claude, planner | $0, local model only | $2 (see below) | $4 |
| Gemini voice notes | $0 | $0.10 | $0.10 |
| Kimi on NIM | $0 | $0, trial | $0, trial |
| AWS compute, c7i.2xlarge Tokyo | $0 | $0 | $27 (60 h) |
| AWS disk, 100 GB gp3 at about $0.088 | $0 | $0 | $8.80 |
| AWS data out, 5 GB | $0 | $0 | under $0.50 |
| **Total** | **about $8.50** | **about $11** | **about $49** |

Claude basis [A]: 30 tasks a month of 5 steps each, 20 staying on Haiku and 10 going to Opus. An Opus step of 8,000 input and 500 output tokens costs $0.012 fully cached ($0.0016 input plus $0.01 output) and $0.042 uncached, so 50 Opus steps cost $0.60 to $2.10. A Haiku step costs about $0.001, so 100 steps cost about $0.10. Adaptive thinking adds output tokens, which is why the typical line sits at the top of that range. Heavy use is double. `SB_MAX_TASK_USD=1.0` (brain `config.py:49`) caps any one task; **no monthly Claude cap exists**, so a runaway rate of tasks is limited only by the owner's account limit.

Heavy AWS means 60 h of mapping a month. A stopped instance still bills its disk, which is why the disk line remains. Delete the worker's volume if mapping stops being useful.

## Guardrails

- AWS budget alarm before first use (HUMAN STEP): $20/month. Budget alerts lag actual spend by hours, so the instance's own timer is the real limit.
- 4 h hard stop on the instance, 15 min idle.
- `SB_AWS_ENABLED=false` by default.
- Every cloud route off until a key is set.
