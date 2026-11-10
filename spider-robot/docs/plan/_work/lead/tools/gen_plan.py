import hashlib, json, pathlib, subprocess, sys, difflib, fnmatch
M = pathlib.Path(__file__).resolve().parents[1]
R = M/"repo"
FENCE = "`"*5
OUT = pathlib.Path("/Users/abdulrahmankawas/Desktop/my_projects/robot_lowi/spider-robot/docs/plan/04_EXECUTION_PLAN.md")
exp_path = M/"expected.json"
EXPECTED = json.loads(exp_path.read_text()) if exp_path.exists() else {}
sys.path.insert(0, str(M/"tools"))
from plan_text import OPENING, HARDWARE_STEPS

def git(*a):
    return subprocess.run(["git","-C",str(R),*a],capture_output=True,text=True,check=True).stdout
status = {}
for line in git("diff","--cached","--name-status","HEAD").splitlines():
    s,p = line.split("\t"); status[p]=s
def old(p): return git("show",f"HEAD:{p}")
def new(p): return (R/p).read_text("utf-8")

def lines(t): return t.splitlines(keepends=True)
def hunks(a,b):
    ops=[o for o in difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes()]
    gs=[]
    for tag,i1,i2,j1,j2 in ops:
        if tag=="equal": continue
        if gs and i1-gs[-1][1]<=2:
            gs[-1][1]=i2; gs[-1][3]=j2
        else: gs.append([i1,i2,j1,j2])
    return gs
def patch_blocks(o,n):
    a,b=lines(o),lines(n)
    gs=hunks(a,b)
    if not gs: return None
    blocks=[]
    for i1,i2,j1,j2 in gs:
        s,e=i1,i2
        if s==e:
            if s>0: s-=1
            else: e+=1
        while True:
            search="".join(a[s:e])
            if o.count(search)==1 and search.endswith("\n") and search.strip(): break
            if s==0 and e==len(a): return None
            if s>0: s-=1
            if e<len(a): e+=1
        blocks.append((s,e,search,"".join(a[s:i1])+"".join(b[j1:j2])+"".join(a[i2:e])))
    # merge overlaps, then simulate
    merged=[]
    for b1 in blocks:
        if merged and b1[0]<merged[-1][1]: return None
        merged.append(b1)
    t=o
    for s,e,sr,rp in merged:
        if t.count(sr)!=1: return None
        t=t.replace(sr,rp)
    if t!=n: return None
    return [(sr,rp) for _,_,sr,rp in merged]

def file_block(p):
    txt=new(p)
    assert FENCE not in txt, p
    assert txt.endswith("\n") or txt=="", p
    sha=hashlib.sha256(txt.encode()).hexdigest()
    out=[]
    st=status[p]
    if st=="A":
        out+=[f"<!-- BEGIN-FILE path={p} mode=new sha256={sha} -->",FENCE,txt[:-1],FENCE,"<!-- END-FILE -->",""] if txt else None
        return out
    o=old(p)
    pb=patch_blocks(o,txt)
    if pb is None or len(lines(o))<60 or len(pb)>30:
        return [f"<!-- BEGIN-FILE path={p} mode=replace sha256={sha} -->",FENCE,txt[:-1],FENCE,"<!-- END-FILE -->",""]
    out=[f"<!-- BEGIN-FILE path={p} mode=patch sha256={sha} -->"]
    for sr,rp in pb:
        out+=["<!-- SEARCH -->",FENCE,sr[:-1],FENCE,"<!-- REPLACE -->",FENCE]
        if rp: out+=[rp[:-1]]
        out+=[FENCE]
    out+=["<!-- END-FILE -->",""]
    return out

SR="spider-robot/"
pkg_test=lambda p,:f"(cd spider-robot/{p} && uv run -q --all-extras --frozen pytest -q 2>&1 | tail -1 && uv run -q --all-extras --frozen ruff check . | tail -1)"
def syn(p, globs):
    return f"(cd spider-robot/{p} && uv run -q --all-extras --frozen ruff check {' '.join(globs)} | tail -1 && uv run -q --all-extras --frozen python -m compileall -q {' '.join(globs)} && echo compiled)"
C=[
("S02","CI workflow and README",[".github/workflows/spider-robot.yml",SR+"README.md"],["python3 -c \"import pathlib; print(len(pathlib.Path('.github/workflows/spider-robot.yml').read_text().splitlines()) > 10)\""],"Add CI workflow and describe the voice package","M0"),
("S03","Wire protocol v3, MQTT link, logging, and their tests",[SR+"common/pyproject.toml",SR+"common/uv.lock",SR+"common/src/spider_common/protocol.py",SR+"common/src/spider_common/link.py",SR+"common/src/spider_common/obs.py",SR+"common/tests/test_protocol.py",SR+"common/tests/test_contract.py"],[pkg_test("common")],"Move the protocol to v3 with confirmed actions and RPC messages","M1"),
("S04","Body packaging, config, real-time setup, E-stop latch",[SR+"body/pyproject.toml",SR+"body/uv.lock",SR+"body/config/robot.example.yaml",SR+"body/src/spider_body/config.py",SR+"body/src/spider_body/rt.py",SR+"body/src/spider_body/safety.py"],[syn("body",["src/spider_body/config.py","src/spider_body/rt.py","src/spider_body/safety.py"])],"Add body real-time setup, broker logins and a persistent E-stop latch","M1"),
("S05","Body hardware drivers",[SR+"body/src/spider_body/hw/servos.py",SR+"body/src/spider_body/hw/lidar.py",SR+"body/src/spider_body/hw/camera.py",SR+"body/src/spider_body/hw/kick.py",SR+"body/src/spider_body/gait.py"],[syn("body",["src/spider_body/hw","src/spider_body/gait.py"])],"Fix servo group timing and merge LiDAR sectors over recent clouds","M1"),
("S06","Body control logic",[SR+"body/src/spider_body/robot.py",SR+"body/src/spider_body/main.py"],[syn("body",["src/spider_body/robot.py","src/spider_body/main.py"])],"Freeze the body under E-stop, stage the wake and start from limp","M1"),
("S07","Camera, recorder and health processes",[SR+"body/src/spider_body/camera_service.py",SR+"body/src/spider_body/recorder.py",SR+"body/src/spider_body/sysmon.py"],[syn("body",["src/spider_body/camera_service.py","src/spider_body/recorder.py","src/spider_body/sysmon.py"])],"Add camera, recorder and system health processes","M1"),
("S08","Body systemd units and LiDAR bridge",[SR+"body/systemd/spider-body.service",SR+"body/systemd/spider-lidar.service",SR+"body/systemd/spider-camera.service",SR+"body/systemd/spider-recorder.service",SR+"body/systemd/spider-sysmon.service",SR+"body/lidar_bridge/lidar_bridge.cpp"],["grep -c network-online spider-robot/body/systemd/*.service | sort | tail -5"],"Order body units on local services only and average the IMU to 50 Hz","M1"),
("S09","Body tests",[SR+"body/tests/test_robot.py",SR+"body/tests/test_safety_fixes.py",SR+"body/tests/test_recorder.py",SR+"body/tests/test_sysmon.py"],[pkg_test("body")],"Add body regression tests for the safety fixes","M1"),
("S10","Gateway packaging, policy and broker ACL",[SR+"gateway/pyproject.toml",SR+"gateway/uv.lock",SR+"gateway/config/gateway.env.example",SR+"gateway/src/spider_gateway/policy.py",SR+"infra/local/acl"],[syn("gateway",["src/spider_gateway/policy.py"])],"Add per-source gateway caps and a broker ACL for every client","M1"),
("S11","Gateway logic, console and release button",[SR+"gateway/src/spider_gateway/gateway.py",SR+"gateway/src/spider_gateway/main.py",SR+"gateway/src/spider_gateway/console.py",SR+"gateway/src/spider_gateway/button.py"],[syn("gateway",["src/spider_gateway"])],"Add stop hold-off, confirmed release, lateness checks and a release button","M1"),
("S12","Gateway systemd units",[SR+"gateway/systemd/spider-gateway.service",SR+"gateway/systemd/spider-button.service"],["grep -c network-online spider-robot/gateway/systemd/*.service | sort | tail -3"],"Start the gateway without waiting for the network","M1"),
("S13","Gateway tests",[SR+"gateway/tests/test_gateway.py",SR+"gateway/tests/test_gateway_policy.py",SR+"gateway/tests/test_acl_contract.py",SR+"gateway/tests/test_console.py",SR+"gateway/tests/test_button.py"],[pkg_test("gateway")],"Add gateway arbitration, ACL contract and button tests","M1"),
("S14","Voice package skeleton and language logic",[SR+"voice/pyproject.toml",SR+"voice/uv.lock",SR+"voice/config/voice.example.yaml",SR+"voice/systemd/spider-voice.service"]+[SR+f"voice/src/spider_voice/{f}.py" for f in "__init__ actions config echo grammar interfaces routing segmenter stopwords text".split()],[syn("voice",["src/spider_voice"])],"Add the voice package with grammar, stop words and routing","M1"),
("S15","Voice audio, RPC and adapters",[SR+f"voice/src/spider_voice/{f}.py" for f in "audio rpc gwclient adapters/__init__ adapters/ask_rpc adapters/router_ollama adapters/stt_chain adapters/stt_rpc adapters/stt_whisper adapters/tts_espeak adapters/tts_piper adapters/vad_webrtc".split()],[syn("voice",["src/spider_voice"])],"Add voice adapters for Whisper, Piper, Ollama and server RPC","M1"),
("S16","Voice pipeline and entry points",[SR+f"voice/src/spider_voice/{f}.py" for f in "pipeline registry main bench".split()],[syn("voice",["src/spider_voice"])],"Add the voice pipeline, service entry point and bench tool","M1"),
("S17","Voice tests",[SR+f"voice/tests/{f}.py" for f in "conftest test_matching test_pipeline test_routing test_segmenter_echo".split()],[pkg_test("voice")],"Add voice pipeline and adapter tests","M1"),
("S18","Brain packaging, config, jobs and workers",[SR+"brain/pyproject.toml",SR+"brain/uv.lock"]+[SR+f"brain/src/spider_brain/{f}.py" for f in "config jobs rec2bag workers observe confirm".split()],[syn("brain",["src/spider_brain/jobs.py","src/spider_brain/workers.py","src/spider_brain/observe.py","src/spider_brain/confirm.py"])],"Add brain workers, confirmed actions, mapping jobs and health alerts","M1"),
]
rest=[p for p in status if p.startswith(SR+"brain/src/") and p not in sum([c[2] for c in C],[])]
C.append(("S19","Brain service, client, Telegram and dashboard",sorted(rest),[syn("brain",["src/spider_brain"])],"Connect the brain to the gateway and its new workers","M1"))
C.append(("S20","Brain tests",sorted(p for p in status if p.startswith(SR+"brain/tests/")),[pkg_test("brain")],"Add brain tests for gateway mode, jobs and the release flow","M1"))
pi=sorted(p for p in status if p.startswith(SR+"infra/pi/") or p in (SR+"infra/local/mosquitto.conf",SR+"infra/local/mosquitto-tls.conf",SR+"infra/local/make_local_certs.sh"))
C.append(("S21","Pi infrastructure",pi,["find spider-robot/infra/pi spider-robot/infra/local -name '*.sh' -print0 | xargs -0 -n1 bash -n && echo shell-ok"],"Add Pi setup, deploy, broker, firewall and tuning files","M1"))
srv=sorted(p for p in status if p.startswith(SR+"infra/server/") or p.startswith(SR+"infra/aws/"))
C.append(("S22","Server and AWS worker infrastructure",srv,["find spider-robot/infra/server spider-robot/infra/aws/worker -name '*.sh' -print0 | xargs -0 -n1 bash -n && python3 -m json.tool spider-robot/infra/aws/worker/worker-control-policy.json >/dev/null && echo shell-and-json-ok"],"Add home server setup and the on-demand AWS worker","M1"))
covered=sum([c[2] for c in C],[])
missing=set(status)-set(covered)
assert not missing, sorted(missing)
extra=[p for p in covered if p not in status]
assert not extra, extra
assert len(covered)==len(set(covered)), "dup"

def code_step(c):
    sid,title,files,checks,msg,ms=c
    prev=f"S{int(sid[1:])-1:02d}"
    cmds=[f"python3 spider-robot/docs/plan/tools/apply_step.py {sid}",*checks,
          f"printf '%s\\n' '{sid} done' >> spider-robot/docs/plan/PROGRESS.md",
          "git add -A spider-robot .github",f'git commit -q -m "{msg}"']
    n=len(files)
    expected=EXPECTED.get(sid,"")
    t=[f"<!-- BEGIN-STEP {sid} -->",f"## {sid}: {title}","",
       f"- **Milestone:** {ms}. **Machine:** Mac. **Directory:** the repository root (the folder holding `.git` and `spider-robot/`).",
       f"- **Goal:** {title}. The code for this step is in the file blocks at the end of this step.",
       f"- **Preconditions:** `{prev} done` is the last line of `spider-robot/docs/plan/PROGRESS.md`, and `git status --short` prints nothing.",
       f"- **Files touched ({n}):**","",*[f"  - `{p}`" for p in files],"",
       "- **Commands**, run exactly these, in order. `apply_step.py` copies the blocks below into place and checks each result by SHA-256; do not retype the blocks:","",
       "```bash",*cmds,"```","",
       f"- **Expected output:** `apply_step.py` prints one `OK` line per file and `{sid}: {n} files written and verified`. Then:","",
       "```",expected,"```","",
       "- **Roll back:** before the commit, `git restore --staged --worktree spider-robot .github && git clean -fd -e spider-robot/docs/plan spider-robot .github`. After the commit, `git revert --no-edit HEAD`.",
       "- **Stop if:** `apply_step.py` prints `STOP`, or any output differs from the expected output, except timings such as `in 3.21s` and the count of warnings. Report the step ID and the exact output.",
       f"- **Commit message:** `{msg}`","",
       "File blocks for this step:",""]
    for p in files: t+=file_block(p)
    t+=[f"<!-- END-STEP {sid} -->",""]
    return t,cmds

S00=[ "<!-- BEGIN-STEP S00 -->","## S00: Baseline commit of existing work","",
 "- **Milestone:** M0. **Machine:** Mac. **Directory:** the repository root (the folder holding `.git` and `spider-robot/`).",
 "- **Goal:** Commit all existing uncommitted work, so every later step can be rolled back. Part of the code exists only in this working tree. Everything uncommitted is included on purpose, among it `CLAUDE.md`, `graphify-out` and the plan files.",
 "- **Preconditions:** You are on the branch the owner gave you. Do not switch branches.",
 "- **Files touched:** every currently uncommitted file; no content changes.","",
 "- **Commands:**","","```bash","uv --version","git config user.name > /dev/null && echo git-identity-ok","git status","git add -A",'git commit -q -m "Baseline of uncommitted spider robot work"',"git status --short | wc -l","```","",
 "- **Expected output:** `uv 0.12.17` with a build suffix, `git-identity-ok`, the status listing, then a final line of `0` (spaces before the digit are fine).",
 "- **Roll back:** `git reset --soft HEAD~1`.",
 "- **Stop if:** the `uv` version differs, `git-identity-ok` does not print, `git commit` fails, or the final line is not `0`. Report the step ID and the exact output.",
 "- **Commit message:** `Baseline of uncommitted spider robot work`","","<!-- END-STEP S00 -->",""]
helper=(M/"tools/apply_step.py").read_text()
hsha=hashlib.sha256(helper.encode()).hexdigest()
S01=["<!-- BEGIN-STEP S01 -->","## S01: Install the file-apply tool and progress log","",
 "- **Milestone:** M0. **Machine:** Mac. **Directory:** the repository root.",
 "- **Goal:** Create `spider-robot/docs/plan/tools/apply_step.py`, which writes each step's file blocks and verifies them, and `PROGRESS.md`.",
 "- **Preconditions:** S00 is done and `git status --short` prints nothing.",
 "- **Files touched:** `spider-robot/docs/plan/tools/apply_step.py`, `spider-robot/docs/plan/PROGRESS.md`.","",
 "- **Commands**, exactly as written, including the heredoc:","","```bash","mkdir -p spider-robot/docs/plan/tools","cat > spider-robot/docs/plan/tools/apply_step.py <<'APPLY_EOF'",helper.rstrip("\n"),"APPLY_EOF",
 f'python3 -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path(\'spider-robot/docs/plan/tools/apply_step.py\').read_bytes()).hexdigest())"',
 "printf '%s\\n' 'S00 done' 'S01 done' > spider-robot/docs/plan/PROGRESS.md","git add -A spider-robot",'git commit -q -m "Add the execution plan file-apply tool and progress log"',"```","",
 f"- **Expected output:** the hash line is exactly `{hsha}`.",
 "- **Roll back:** `git revert --no-edit HEAD`.",
 "- **Stop if:** the hash differs. Report the step ID and the exact output.",
 "- **Commit message:** `Add the execution plan file-apply tool and progress log`","","<!-- END-STEP S01 -->",""]
S23cmds=[pkg_test(p) for p in "common body gateway voice brain".split()]+["for p in common body gateway voice brain; do (cd spider-robot/$p && uv lock --check 2>&1 | tail -1); done","printf '%s\\n' 'S23 done' >> spider-robot/docs/plan/PROGRESS.md","git add -A spider-robot",'git commit -q -m "Record that all packages pass after the merged plan"']
S23=["<!-- BEGIN-STEP S23 -->","## S23: Full check of every package","",
 "- **Milestone:** M1 gate. **Machine:** Mac. **Directory:** the repository root.",
 "- **Goal:** Prove every package passes tests and lint together, and that lock files are current.",
 "- **Preconditions:** `S22 done` is the last line of `spider-robot/docs/plan/PROGRESS.md`.",
 "- **Files touched:** `spider-robot/docs/plan/PROGRESS.md`.","",
 "- **Commands:**","","```bash",*S23cmds,"```","",
 "- **Expected output:**","","```",EXPECTED.get("S23",""),"```","",
 "- **Roll back:** nothing to undo beyond the progress line: `git revert --no-edit HEAD`.",
 "- **Stop if:** any package reports a failure or `ruff` does not print `All checks passed!`. Report the step ID and the exact output.",
 "- **Commit message:** `Record that all packages pass after the merged plan`","","<!-- END-STEP S23 -->",""]
body=list(S00)+list(S01)
allcmds={"S00":None}
for c in C:
    t,cmds=code_step(c)
    body+=t; allcmds[c[0]]=cmds
body+=S23
allcmds["S23"]=S23cmds
body+=HARDWARE_STEPS
json.dump({k:v for k,v in allcmds.items() if v},open(M/"allcmds.json","w"),indent=1)

# index: flatten first, because file blocks are single list items holding many lines
body="\n".join(body).split("\n")
def build(index_lines):
    return OPENING+["## Index","","| Step | Title | Lines |","|---|---|---|",*index_lines,""]+body
ids=[]
for i,l in enumerate(body):
    if l.startswith("<!-- BEGIN-STEP "):
        sid=l.split()[2]
        title=body[i+1].split(": ",1)[1]
        end=body.index(f"<!-- END-STEP {sid} -->",i)
        ids.append((sid,title,i,end))
dummy=[f"| {s} | {t} | 00000-00000 |" for s,t,_,_ in ids]
head=len(OPENING)+4+len(dummy)+1
index=[f"| {s} | {t} | {head+a+1}-{head+b+1} |" for s,t,a,b in ids]
text="\n".join(build(index))+"\n"
check=text.split("\n")
for s,_t,a,b in ids:
    assert check[head+a]==f"<!-- BEGIN-STEP {s} -->" and check[head+b]==f"<!-- END-STEP {s} -->",(s,head,a,b)
OUT.write_text(text,"utf-8")
print("lines",text.count("\n"),"steps",len(ids),"bytes",len(text.encode()))
