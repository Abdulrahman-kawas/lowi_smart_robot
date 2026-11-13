# 7. Security

## 7.1 Assets and trust

Assets: the robot's motion, the camera and microphone in a private home, the owner's API keys, the server.

Trust boundaries: internet to server; tailnet to Pi; camera, mic and any spoken or visible text into the models; processes on the Pi.

The main design rule: **a compromised brain or Telegram account must not be able to do what the gateway forbids.**

## 7.2 STRIDE

| Threat | Asset or path | S T R I D E | Mitigation | Status | Residual |
|---|---|---|---|---|---|
| **Telegram account takeover** | Owner identity | S E | Only `SB_TELEGRAM_OWNER_IDS` served (`telegram.py:144`). Owner must enable two-step verification. An attacker is still bound by Pi-side caps: 0.06 m/s, 1.5 s Moves, body reflexes, no wake or release without a frame | Exists plus patch | **High impact: they can view the camera, send tasks, approve motion, and confirm a release, since they would see the same frame. Physical E-stop and the owner's Telegram active-session alerts are the answer** |
| Telegram bot token theft | Bot | S | `secrets.env` mode 600; rotate through BotFather | Patch | Low: attacker still needs an owner ID to be served. They can read updates, so rotate at once |
| Spoofed MQTT client | Broker | S | Remote listener requires a client certificate, CN is the identity; loopback needs a password | Patch | Low |
| Forged commands to the body | `cmd` | S E | ACL: only `spider-gateway` writes `cmd`. Tested against every client | Patch | Low |
| Source impersonation | `gw/voice/cmd` | S E | ACL: brain cannot write voice; voice cannot write remote. Tested | Patch | Brain certificate covers both remote and planner by design |
| Tampering in transit | MQTT over Tailscale | T I | WireGuard plus TLS on the remote listener. Loopback does not leave the Pi | Patch | Low |
| Replay of a release | Challenge | T | Single-use, 30 s, bound to action, source and frame hash | Patch, tested | Low |
| Replay of old commands | Broker restart | T | `persistence false`, `clean_session`, age check, fence | Patch | Low |
| Forged frame shown to owner | Confirmation | T | Brain checks the frame's hash against the gateway's. Both come from the Pi | Patch, tested | A compromised Pi defeats it |
| **Ollama or model servers exposed** | Pi 11434; server 8080, 8081 | I D E | All loopback. Pi firewall drops 11434 and 1883 from non-loopback. No model port on the tailnet | Patch | Low |
| **Prompt injection through camera** | Vision answer | T E | `AskReply` has no action, tested. Planner gets answers wrapped as observations (`tools.py:216-218`), and every Move needs approval at `guarded` (`policy.py:29-33`) | Exists plus patch | At `autonomous` an injected observation can influence the planner. **Keep `guarded`**, as Decision 8 says |
| **Prompt injection through voice** | Router | T E | Output is limited to an enum. Injection can at most choose one short capped motion. Wake word required | Patch | Anyone in the room can command it; that is the product |
| Injection through forwarded Telegram text | Planner | T E | Owner's own messages; approvals | Exists | Low |
| Injection into memory | `remember` | T | Facts are treated as data; `/memory` and `/forget` audit them | Exists | Medium: a poisoned fact persists until removed |
| Long question or audio flood | Workers | D | Size limits in the models; single-flight; `busy` reply | Patch, tested | Low |
| Broker flood from a bad local process | Broker | D | `max_queued_messages`, size limit, cgroup caps | Patch | Low |
| Privacy of camera and audio | Frames, transcripts | I | Stays at home by default. Cloud only if a fallback is configured, and then the frame goes to the provider. Traces store 200 characters of text in a local file | Patch | Owner choice. Disclose to guests |
| Dashboard exposed | Web UI | S I | Loopback plus `tailscale serve`, origin check, token (`server.py:51-62`) | Exists | The `/#t=` token is printed in the log. Keep journal access private |
| Telegram token in logs | Secrets | I | Never logged by this code; httpx at INFO would show URLs including the token. Keep httpx at WARNING | Note | Check in M3 |
| Stolen SD card | All secrets | I | Not encrypted. Certificates and keys can be revoked | Accepted | Medium |
| Stolen server | API keys | I | Disk encryption is the owner's choice | Accepted | Medium |
| No audit of who moved it | History | R | JSON logs with `cid`; Telegram holds its own record; gateway counters | Patch | Logs on the Pi are in RAM. Brain traces persist |
| AWS credential theft | AWS | E | Policy allows only start and stop on one instance, plus describe. Pi holds none | Patch | Low: attacker can run up the one instance's bill; budget alarm |
| Malicious model file | Supply chain | T E | Pinned tags and hashes in `uv.lock`; GGUF is data. Pin model commit in M3 | Partial | Low |

## 7.3 Secrets

| Secret | Where | Mode |
|---|---|---|
| MQTT passwords, per process | `/etc/spider/secrets/*.mqtt` | 400, user `spider` |
| Broker password hashes | `/etc/mosquitto/spider/passwords` | 640 root:mosquitto |
| Brain client certificate key | `/etc/spider-brain/certs/` | 600 |
| Telegram, Anthropic, Gemini, NIM keys | `/etc/spider-brain/secrets.env` | 600, read by systemd |
| AWS keys | Same file, scoped to the policy | 600 |
| CA private key | **Offline, not on Pi or server** | - |

The Pi holds no API keys and no AWS credentials.

## 7.4 Certificate rotation

Certificates are used only by the remote listener, so a mistake cannot take local control down.

| Step | Action |
|---|---|
| Schedule | Yearly, or at once after suspected compromise; alert 30 days before the 825-day expiry |
| 1 | On the offline machine, `BROKER_HOST=<pi> BROKER_IP=<ip> ./make_local_certs.sh` with a new client certificate |
| 2 | Copy to the Pi and server, robot sitting |
| 3 | `sudo systemctl restart mosquitto`, then `spider-brain` |
| 4 | Confirm `spider-brain status` works |
| On compromise | Replace the CA and all certificates. The script as written does not produce a CRL, so replacing the CA is the only revocation |

## 7.5 Tailscale policy (owner applies once)

```json
{
  "tagOwners": {"tag:robot": ["autogroup:admin"], "tag:server": ["autogroup:admin"]},
  "acls": [
    {"action": "accept", "src": ["tag:server"], "dst": ["tag:robot:8883,22"]},
    {"action": "accept", "src": ["autogroup:admin"], "dst": ["tag:server:443", "tag:robot:22"]}
  ]
}
```

Tailnet ACLs are a separate layer from the Pi's nftables rules and the broker's ACL; a mistake in one does not open the others.
