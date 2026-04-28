# SAM Cloud NAT Setup — IP Rotation for Scraping

## Why
Blinkit/Jiomart Cloud Run ke single IP se requests aate hain to block hone ka chance hai. 25 IPs rotate karne se har request alag IP se jayega — platforms ko lagega 25 alag users hain.

## Architecture
```
Cloud Run (price-scraper-daily)
    ↓
sam-vpc-connector (bridge: Cloud Run → VPC)
    ↓
default network → sam-subnet (10.9.0.0/24)
    ↓
sam-router → sam-nat (25 IPs rotate)
    ↓
Internet → Blinkit / Jiomart
```

## What We Created (all `sam-*`, nothing else touched)

| Resource | Name | Details |
|----------|------|---------|
| VPC Connector | `sam-vpc-connector` | Region: asia-south1, Network: default, Range: 10.8.0.0/28 |
| Cloud Router | `sam-router` | Region: asia-south1, Network: default |
| Static IPs | `sam-ip-1` to `sam-ip-25` | 25 external IPs in asia-south1 |
| VPC Network | `sam-network` | Isolated custom network, not shared with anyone |
| Subnet | `sam-subnet-v2` | Region: asia-south1, Range: 10.9.0.0/28 |
| Cloud Router | `sam-router-v2` | In sam-network (old sam-router on default deleted) |
| Cloud NAT | `sam-nat` | On sam-router-v2, 25 IPs, all sam-network traffic |

## What's NOT Touched
- `kinetic-router` — untouched
- `kinetic-nat` — untouched
- `default` subnet (10.160.0.0/20) — untouched
- No other project/service affected

## Remaining Steps
1. Create `sam-subnet` in default network (10.9.0.0/24)
2. Create `sam-nat` on `sam-router` with 25 IPs, mapped to `sam-subnet` only
3. Recreate `sam-vpc-connector` on `sam-subnet` (currently on auto-range 10.8.0.0/28)
4. Update Cloud Run job to use `sam-vpc-connector` with egress = all-traffic
5. Test: run Ranchi scrape → check if different IPs used

## Cloud Run Job Update Command (after NAT is ready)
```bash
gcloud run jobs update price-scraper-daily \
  --vpc-connector=sam-vpc-connector \
  --vpc-egress=all-traffic \
  --region asia-south1 \
  --project apna-mart-data
```

## Cost Estimate
- VPC Connector: ~$7/month (f1-micro × 2 instances)
- Cloud NAT: ~$1/month
- 25 Static IPs: ~$5/month (attached = $0.004/hr each)
- **Total: ~$13-15/month**

## IP List
```
sam-ip-1:  34.93.224.249
sam-ip-2:  34.93.241.179
sam-ip-3:  34.93.82.136
sam-ip-4:  34.93.202.48
sam-ip-5:  34.180.8.255
sam-ip-6:  34.93.206.76
sam-ip-7:  35.244.4.84
sam-ip-8:  34.47.193.85
sam-ip-9:  34.93.72.253
sam-ip-10: 35.200.187.97
sam-ip-11: 34.47.213.174
sam-ip-12: 34.14.184.136
sam-ip-13: 34.93.208.228
sam-ip-14: 34.100.199.172
sam-ip-15: 34.100.136.94
sam-ip-16 to sam-ip-25: allocated in asia-south1
```

## How IP Rotation Works
- Cloud NAT automatically assigns different IP from pool for each new connection
- 25 IPs = Blinkit/Jiomart sees 25 different "users"
- No code change needed — rotation happens at network level
- Works for both Blinkit (Cloudflare) and Jiomart (Akamai)
