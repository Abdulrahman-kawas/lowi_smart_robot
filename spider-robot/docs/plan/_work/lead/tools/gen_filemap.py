import pathlib, subprocess, re, sys, json
M=pathlib.Path(__file__).resolve().parents[1]; R=M/"repo"
sys.argv=["x"]
src=(M/"tools/gen_plan.py").read_text()
# reuse the step table by executing the generator's definitions up to code_step
ns={"__file__":str(M/"tools/gen_plan.py")}
exec(src[:src.index("def code_step(c):")],ns)
C=ns["C"]; status=ns["status"]
step={}
for c in C:
    for p in c[2]: step[p]=(c[0],c[5])
nodes=lambda p: ("Mac / CI" if p.startswith(".github") or "/tests/" in p or p.endswith("uv.lock") or "README" in p or "make_local_certs" in p
   else "Home server" if "/brain/" in p or "/infra/server/" in p else "AWS worker" if "/infra/aws/" in p else "Pi")
owner=lambda p: (("repo" if p.count("/")==1 else p.split("/")[1]) if p.startswith("spider-robot/") else "ci")
def purpose(p):
    f=R/p
    t=f.read_text("utf-8")
    if p.endswith("uv.lock"): return "Pinned dependency versions"
    if p.endswith("pyproject.toml"): return "Package metadata, dependencies and entry points"
    if p.endswith(".py"):
        m=re.match(r'\s*(?:#![^\n]*\n)?\s*"""(.+?)(?:\n|""")',t)
        if m: return m.group(1).strip().replace("|","/")
        name=f.stem.replace("test_","").replace("_"," ")
        return f"Tests: {name}" if "/tests/" in p else f"Module {f.stem}"
    if p.endswith(".service") or p.endswith(".timer"):
        m=re.search(r"Description=(.+)",t)
        if m: return "systemd unit: "+m.group(1)
    for line in t.splitlines()[:6]:
        l=line.strip("#/ ").strip()
        if l and not l.startswith("!") and not l.startswith("usr/") and len(l)>12: return l[:150].replace("|","/")
    return f.name
rows=[]
for p in sorted(status):
    a="Create" if status[p]=="A" else "Change"
    s,ms=step[p]
    rows.append(f"| `{p}` | {a} | {purpose(p)} | {owner(p)} | {nodes(p)} | {ms}, {s} |")
head=f"""# Spider robot: file map

Every file the plan creates or changes, generated from the merged code, so it cannot disagree with
`04_EXECUTION_PLAN.md`. Total: {len(rows)} files, {sum(1 for p in status if status[p]=="A")} created and
{sum(1 for p in status if status[p]!="A")} changed. "Node" is where the file runs. Code steps all
execute on the Mac; the Pi and server receive the files later, in steps P02 and Q01.

| Path | Action | Purpose | Owner package | Node | Milestone, step |
|---|---|---|---|---|---|
"""
tail="""
## Files added only as tools of the plan

| Path | Action | Purpose | Node | Step |
|---|---|---|---|---|
| `spider-robot/docs/plan/tools/apply_step.py` | Create | Writes each step's file blocks and verifies them by SHA-256 | Mac | M0, S01 |
| `spider-robot/docs/plan/PROGRESS.md` | Create | Last finished step, so a new session can resume | Mac | M0, S01 |
| `spider-robot/docs/plan/BENCH_RESULTS.md` | Create | Real bench results, added by the owner | Mac | M2 onward |

## Deleted

Nothing is deleted until M8. Then, once M6 has run for two weeks and the owner approves (step Q05):

| Path | Why |
|---|---|
| `spider-robot/infra/ec2/` | Replaced by the home server |
| `spider-robot/infra/aws/iot_setup.sh`, `body-policy.json`, `brain-policy.json` | AWS IoT is dropped from the base design |

The architecture says to keep these until the home server has replaced them.

## Kept unchanged

`body/src/spider_body/kinematics.py`, `calibrate.py`; the corridor logic in `safety.py`; the brain's
planner, graph, tools, policy, memory, skills and dashboard server structure; `infra/local/mosquitto-sim.conf`.
"""
pathlib.Path("/Users/abdulrahmankawas/Desktop/my_projects/robot_lowi/spider-robot/docs/plan/02_FILE_MAP.md").write_text(head+"\n".join(rows)+"\n"+tail,"utf-8")
print(len(rows))
