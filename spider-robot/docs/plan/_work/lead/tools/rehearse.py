import json, pathlib, subprocess, shutil, re, sys
M=pathlib.Path(__file__).resolve().parents[1]
RH=M/"rehearse"
ROOT="/Users/abdulrahmankawas/Desktop/my_projects/robot_lowi/"
if RH.exists(): shutil.rmtree(RH)
subprocess.run(["rsync","-a","--exclude",".venv","--exclude","__pycache__","--exclude",".pytest_cache","--exclude",".ruff_cache",ROOT,str(RH)+"/"],check=True)
def sh(c):
    return subprocess.run(["bash","-c",c],cwd=RH,capture_output=True,text=True)
for c in ["git add -A",'git commit -q -m "Baseline of uncommitted spider robot work"']:
    r=sh(c); assert r.returncode==0,(c,r.stdout,r.stderr)
tools=RH/"spider-robot/docs/plan/tools"; tools.mkdir(parents=True,exist_ok=True); shutil.copy(M/"tools/apply_step.py",tools/"apply_step.py")
(RH/"spider-robot/docs/plan/PROGRESS.md").write_text("S00 done\nS01 done\n")
sh('git add -A spider-robot && git commit -q -m "Add the execution plan file-apply tool and progress log"')
cmds=json.load(open(M/"allcmds.json"))
exp={}
ok=True
for sid,cl in cmds.items():
    outs=[]
    for c in cl:
        r=sh(c)
        if not (c.startswith("python3 spider-robot/docs/plan/tools") or c.startswith("printf") or c.startswith("git ")):
            outs.append(r.stdout.strip())
        if r.returncode!=0:
            print("FAIL",sid,c,r.stdout[-1500:],r.stderr[-1500:]); ok=False; break
    exp[sid]="\n".join(outs)
    print(sid,"|",exp[sid].replace("\n"," / ")[:160],flush=True)
    if not ok: break
if ok:
    (M/"expected.json").write_text(json.dumps(exp,ensure_ascii=False,indent=1))
    print("ALL OK")
