# 7. Security: STRIDE

Assets, in order: physical safety, the owner's home (camera and microphone), credentials, the API
budget. Trust boundaries: the phone and Telegram; the tailnet; the Pi's loopback; the cloud.

## 7.1 Threats

| ID | STRIDE | Threat | Controls | Residual |
|---|---|---|---|---|
| T-01 | Spoofing | **Telegram account taken over** | Only `SB_TELEGRAM_OWNER_IDS` served (`telegram.py:144-148`); two-step verification required (runbook). Even so: gateway caps bound speed and duration; motion approvals; E-stop release needs a fresh photo | An attacker with the account has the owner's remote powers within the caps, and can see the camera. Revoke through Telegram and rotate the bot token (runbook) |
| T-02 | Spoofing | Bot token stolen | Token only in `/etc/spider-brain/brain.env`, mode 600. Long polling, no open port. Thief cannot pose as the owner: `from.id` is set by Telegram | They could read incoming updates. Rotate |
| T-03 | Spoofing | A process claims to be another source | Broker ACL binds each certificate to its own `gw/<source>/cmd` topic; source identity comes from the topic | None within the broker |
| T-04 | Spoofing | Rogue MQTT client | mTLS required, `allow_anonymous false`, firewall limits the port to loopback and tailnet | CA key theft; kept offline |
| T-05 | Tampering | Commands altered in transit | TLS; WireGuard on the tailnet | Negligible |
| T-06 | Tampering | **Prompt injection through the camera** | Vision has no tools. Answers on the Pi are spoken only: no code path to a command. Planner receives them marked as untrusted (`tools.py:216-219`), under approvals | A spoken lie; motion unaffected |
| T-07 | Tampering | **Prompt injection through voice** | Wake gate; grammar first; `cross_check` limits the LLM to motions named in the words; caps; stop words stripped from speech | Someone in the room can command the robot by voice. By design |
| T-08 | Tampering | Forged `snapshot_ok` to bypass the release rule | Only the body and camera certificates may write `event` | Compromise of a Pi service; then the attacker already has more |
| T-09 | Tampering | Compromised brain forges `confirmed=true` | The human check is enforced by the brain; the frame rule by the gateway; the Pi cannot verify a human | A compromised server can release an E-stop with a real fresh frame. The physical E-stop is unaffected: it does not listen to software |
| T-10 | Repudiation | Who commanded what | `trace` id from utterance or task to motion; `VoiceTurn` kept on the server; body and gateway events | Logs on the Pi are volatile by design |
| T-11 | Information | Camera or audio leak | Audio stays on the Pi unless a hard utterance escalates to the owner's own server; frames on request only; `voice.yaml` must opt in to cloud services; Claude does not see images unless `claude_sees_images` is set | Cloud providers see what is sent to them when enabled |
| T-12 | Information | Secrets in the repository | Placeholders only; `.gitignore` covers keys; CI scans for key patterns | A novel key format |
| T-13 | Information | **Ollama or llama-server exposed** | Pi's Ollama binds to 127.0.0.1. Server's `llama-server` binds to the Tailscale address and needs an API key; `spider-stt` the same with a token | Anyone authorised on the tailnet still needs the key |
| T-14 | Denial | Message flood | Gateway per-source caps on Snapshot; bounded inboxes; broker queue limits. Voice loop bounded to one long utterance | Sustained flood of commands from a valid client; such a client is already trusted |
| T-15 | Denial | Loud audio keeps Whisper busy | Runs on cores 1-3 only; RT1 proves the control loop holds | Voice degraded during the noise |
| T-16 | Denial | Wi-Fi jamming | Motion expires; local voice remains | Remote control lost |
| T-17 | Elevation | Service compromise reaches the system | Each service runs as `spider`, `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`; only `spider-body` has `CAP_SYS_NICE` and `CAP_IPC_LOCK` | All Pi services share one user, so a compromise of one can read the others' keys. Accepted for one robot; separate users are a later hardening |
| T-18 | Elevation | AWS credential abuse | Only on the server; policy allows start and stop of one instance, plus describe, which AWS does not allow to be scoped per instance | Describe leaks instance inventory |
| T-19 | Elevation | Supply chain | Everything pinned: `uv.lock`, exact model tags, exact Ollama and llama.cpp versions | A malicious pinned release |
| T-20 | Spoofing | Dashboard reached by another device | Loopback only (`config.py:135-143`), `tailscale serve`, origin allowlist, per-run token | Stolen run token |

## 7.2 Network policy

Pi firewall: `infra/pi/nftables-spider.conf`. Default drop. Accept SSH and 8883 on `tailscale0`, SSH
from the home LAN for recovery, Tailscale UDP, and the LiDAR's UDP from the LiDAR's address only.

Tailscale ACL, set by the owner in the admin console:

```json
{
  "tagOwners": {"tag:robot": ["autogroup:owner"], "tag:server": ["autogroup:owner"], "tag:worker": ["autogroup:owner"]},
  "grants": [
    {"src": ["autogroup:owner"], "dst": ["tag:robot"], "ip": ["22"]},
    {"src": ["autogroup:owner"], "dst": ["tag:server"], "ip": ["443", "22"]},
    {"src": ["tag:server"], "dst": ["tag:robot"], "ip": ["22", "8883"]},
    {"src": ["tag:robot"], "dst": ["tag:server"], "ip": ["8080", "8081", "8090"]},
    {"src": ["tag:server"], "dst": ["tag:worker"], "ip": ["22"]}
  ]
}
```

## 7.3 Secrets

| Secret | Location | Mode | Rotation |
|---|---|---|---|
| Mosquitto CA key | Offline, on the owner's laptop | 600 | With the CA, every 10 years, or on compromise |
| Client and server keys | `/etc/spider/certs`, `/etc/spider-brain/certs` | 600 | 825-day validity. Check quarterly: `openssl x509 -checkend 5184000 -noout -in FILE` |
| Telegram token, API keys | `/etc/spider-brain/brain.env` | 600 | On suspicion, through each provider |
| `llama-server` key, STT token | `/etc/spider-brain/*.env`, `/etc/spider/voice.yaml` | 600 / 640 | Quarterly |
| AWS credentials | Server only, scoped user | 600 | Quarterly. **The Pi never holds any** |

### Certificate rotation

1. On the laptop, delete the pair: `rm spider-voice.{crt,key}`, then run `make_local_certs.sh`. It
   issues only what is missing.
2. Copy the pair to the service's directory, mode 600, owner `spider`.
3. `systemctl restart spider-voice`.
4. The server certificate is the same, followed by `systemctl restart mosquitto`. Everything reconnects
   by itself.

A compromised client certificate has no revocation list in this design. Remove its user from the ACL
and restart Mosquitto, then issue a new one. For a CA compromise, reissue everything.
