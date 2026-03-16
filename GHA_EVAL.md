# GitHub Actions 기반 평가 타당성 검증 실험

> **목적**: EnvBench의 Docker 기반 Linux 평가와 GitHub Actions ubuntu-22.04 기반 평가가 동등한 결과를 내는지 확인한다.
> 이를 통해 GHA 크로스 플랫폼 평가 프레임워크의 Linux 결과를 EnvBench 논문 결과와 직접 비교할 수 있는 근거를 확보한다.

---

## 1. 이 실험이 왜 필요한가

### 논문에서의 역할

본 연구의 핵심 기여는 **GitHub Actions 기반 크로스 플랫폼 평가 프레임워크**다.
Windows와 macOS 결과를 EnvBench 논문 수치와 비교하려면, 먼저 Linux에서 두 방법이 동등함을 보여야 한다.

```
EnvBench 논문 (Docker Linux)
        ↕  ← 이 실험이 검증하는 부분
GHA ubuntu-22.04  →  GHA windows-2022  →  GHA macos-13
```

리뷰어가 반드시 묻는 질문: *"Docker 환경과 GHA 환경은 다른데, 결과가 comparable한가?"*

### 두 환경의 차이

| 항목 | EnvBench Docker | GHA ubuntu-22.04 |
|------|----------------|-----------------|
| 베이스 OS | Ubuntu 22.04 | Ubuntu 22.04 |
| Python 관리 | pyenv (3.8–3.13 설치됨) | pre-installed system Python + conda |
| pip/poetry | 수동 설치 | pre-installed |
| 네트워크 | Docker bridge | GHA runner network |
| 평가 도구 | pyright (컨테이너 내) | pyright (runner 직접) |

이 차이가 `pass@1`에 얼마나 영향을 미치는지 정량화하는 것이 이 실험의 목표다.

---

## 2. 실험 설계

### 전략: 동일 에이전트, 동일 레포, 두 환경

```
[동일 50개 레포 샘플]
         │
    ┌────┴────┐
    ▼         ▼
[Docker eval]  [GHA ubuntu eval]
(EnvBench 기존) (새로운 방법)
    │              │
    ▼              ▼
 results_A      results_B
    │              │
    └──────┬───────┘
           ▼
    pass@1 비교, avgErrs 비교
    Pearson 상관계수, Cohen's Kappa
```

### 핵심 설계 결정

- **에이전트**: EnvBench Bash Agent (GPT-4o) — 동일 에이전트, 동일 프롬프트
- **레포 샘플**: 기존 `bash_agent-4o` 결과(327개)에서 50개 stratified sampling
  - stratify by: pass/fail 비율, 의존성 관리자(pip/poetry/conda), star count
- **메트릭**: `pass@1` (exit_code==0 AND issues_count==0), `avgErrs`
- **평가 방법 (GHA)**: pyright `--outputjson` 직접 실행 (Docker 내부와 동일 기준)
- **시드 고정**: 재현성을 위해 `random.seed(42)`

---

## 3. 사전 준비

### 3-1. 기존 Docker 결과 확인

```bash
cd /path/to/EnvAgent-multi

# 기존 결과 파일 확인 (327개 레포)
ls EnvBench-trajectories/python/bash_agent-4o/
# results.jsonl  scripts.jsonl  trajectories/

# pass@1 계산
python3 - << 'EOF'
import json
with open("EnvBench-trajectories/python/bash_agent-4o/results.jsonl") as f:
    results = [json.loads(l) for l in f]
total = len(results)
passed = sum(1 for r in results if r.get("exit_code") == 0 and r.get("issues_count", 1) == 0)
avg_err = sum(r.get("issues_count", 0) for r in results) / total
print(f"Docker baseline: {total} repos")
print(f"pass@1 = {passed}/{total} = {passed/total*100:.1f}%")
print(f"avgErrs = {avg_err:.2f}")
EOF
```

### 3-2. 50개 stratified 샘플 추출

```python
# scripts/sample_repos.py
import json
import random

random.seed(42)

with open("EnvBench-trajectories/python/bash_agent-4o/results.jsonl") as f:
    results = [json.loads(l) for l in f]

# Stratify by pass/fail
passed = [r for r in results if r.get("exit_code") == 0 and r.get("issues_count", 1) == 0]
failed = [r for r in results if not (r.get("exit_code") == 0 and r.get("issues_count", 1) == 0)]

# 비율 유지하며 50개 샘플 (pass:fail = 기존 비율)
pass_ratio = len(passed) / len(results)
n_pass = round(50 * pass_ratio)
n_fail = 50 - n_pass

sample_pass = random.sample(passed, n_pass)
sample_fail = random.sample(failed, n_fail)
sample = sample_pass + sample_fail
random.shuffle(sample)

# repo 이름과 commit SHA만 추출 (GHA에서 클론용)
with open("data/gha_validation_sample50.jsonl", "w") as f:
    for r in sample:
        entry = {
            "repo_name": r["repo_name"],
            "commit_sha": r.get("commit_sha", ""),
        }
        f.write(json.dumps(entry) + "\n")

print(f"Saved {len(sample)} repos (pass={n_pass}, fail={n_fail})")
print(f"Expected pass@1 ~ {pass_ratio*100:.1f}%")
```

```bash
mkdir -p data
python3 scripts/sample_repos.py
# → data/gha_validation_sample50.jsonl 생성
```

### 3-3. EnvBench 데이터셋에서 샘플의 full metadata 가져오기

```python
# scripts/enrich_sample.py
import json

# EnvBench 전체 dataset (HuggingFace 또는 로컬)
with open("EnvBench/data/oss_python.jsonl") as f:
    all_repos = {json.loads(l)["repo_name"]: json.loads(l) for l in f}

with open("data/gha_validation_sample50.jsonl") as f:
    sample = [json.loads(l) for l in f]

enriched = []
for entry in sample:
    full = all_repos.get(entry["repo_name"], entry)
    enriched.append(full)

with open("data/gha_validation_sample50_full.jsonl", "w") as f:
    for r in enriched:
        f.write(json.dumps(r) + "\n")

print(f"Enriched {len(enriched)} repos")
```

---

## 4. Docker 평가 결과 추출 (기존 결과 재활용)

GHA와 비교할 Docker 기준값을 50개 샘플로 필터링한다.
새로 실험할 필요 없이 **기존 결과를 재활용**한다.

```python
# scripts/extract_docker_baseline.py
import json

with open("EnvBench-trajectories/python/bash_agent-4o/results.jsonl") as f:
    all_results = {json.loads(l)["repo_name"]: json.loads(l) for l in f}

with open("data/gha_validation_sample50.jsonl") as f:
    sample_repos = {json.loads(l)["repo_name"] for l in f}

# 샘플에 해당하는 Docker 결과만 추출
docker_sample = [v for k, v in all_results.items() if k in sample_repos]

with open("results/docker_baseline_sample50.jsonl", "w") as f:
    for r in docker_sample:
        f.write(json.dumps(r) + "\n")

# 메트릭 계산
total = len(docker_sample)
passed = sum(1 for r in docker_sample if r.get("exit_code") == 0 and r.get("issues_count", 1) == 0)
avg_err = sum(r.get("issues_count", 0) for r in docker_sample) / total

print(f"Docker sample (n={total}): pass@1={passed/total*100:.1f}%, avgErrs={avg_err:.2f}")
```

```bash
mkdir -p results
python3 scripts/extract_docker_baseline.py
```

---

## 5. GitHub Actions 워크플로우 구현

### 5-1. 워크플로우 파일 생성

```bash
mkdir -p .github/workflows
```

`.github/workflows/gha_linux_validation.yml`:

```yaml
name: GHA Linux Validation (vs Docker baseline)

on:
  workflow_dispatch:
    inputs:
      repos_jsonl:
        description: 'JSONL file with repos to evaluate (path in repo)'
        default: 'data/gha_validation_sample50_full.jsonl'
      model:
        description: 'OpenAI model'
        default: 'gpt-4o'
      max_iterations:
        description: 'Max agent iterations per repo'
        default: '30'

jobs:
  evaluate:
    runs-on: ubuntu-22.04
    timeout-minutes: 30  # 레포당 최대 30분

    strategy:
      fail-fast: false
      matrix:
        # JSONL을 청크로 분할하여 병렬 실행 (아래 prepare job에서 설정)
        chunk: [0, 1, 2, 3, 4]  # 50개 ÷ 5 = 청크당 10개

    steps:
      # ── 환경 준비 ──────────────────────────────────────────
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install pyenv (Docker 환경과 동일하게)
        run: |
          curl https://pyenv.run | bash
          echo 'export PYENV_ROOT="$HOME/.pyenv"' >> $GITHUB_ENV
          echo 'export PATH="$HOME/.pyenv/bin:$HOME/.pyenv/shims:$PATH"' >> $GITHUB_ENV
          echo "$HOME/.pyenv/bin" >> $GITHUB_PATH
          echo "$HOME/.pyenv/shims" >> $GITHUB_PATH
          # Docker 이미지와 동일한 Python 버전 설치
          $HOME/.pyenv/bin/pyenv install 3.13.1 3.12.8 3.11.11 3.10.16 3.9.21 3.8.20

      - name: Install evaluation tools
        run: |
          pip install openai pyright

      - name: Install EnvBench inference dependencies
        run: |
          cd EnvBench
          pip install uv
          uv venv --python 3.11
          source .venv/bin/activate
          uv sync

      # ── 에이전트 실행 ─────────────────────────────────────
      - name: Prepare chunk repos
        id: chunk
        run: |
          python3 - << 'EOF'
          import json, os, sys

          chunk_id = int(os.environ.get("CHUNK_ID", "${{ matrix.chunk }}"))
          chunk_size = 10  # 50개 / 5청크

          with open("data/gha_validation_sample50_full.jsonl") as f:
              repos = [json.loads(l) for l in f]

          start = chunk_id * chunk_size
          chunk = repos[start:start + chunk_size]

          with open(f"data/chunk_{chunk_id}.jsonl", "w") as f:
              for r in chunk:
                  f.write(json.dumps(r) + "\n")

          print(f"Chunk {chunk_id}: repos {start}–{start+len(chunk)-1} ({len(chunk)} repos)")
          EOF
        env:
          CHUNK_ID: ${{ matrix.chunk }}

      - name: Run Bash Agent on chunk
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          cd EnvBench
          source .venv/bin/activate

          # EnvBench Bash Agent 실행 (기존과 동일 설정)
          python inference/main.py \
            --config-name python-bash \
            +inference.data_source.local.path=../data/chunk_${{ matrix.chunk }}.jsonl \
            +inference.output_dir=../scripts_out/gha_chunk_${{ matrix.chunk }} \
            inference.agent.max_iterations=${{ github.event.inputs.max_iterations }} \
            inference.llm.model=${{ github.event.inputs.model }} \
            inference.llm.temperature=0

      # ── 평가 (pyright) ────────────────────────────────────
      - name: Evaluate bootstrap scripts with pyright
        run: |
          python3 scripts/gha_evaluate.py \
            --scripts-dir scripts_out/gha_chunk_${{ matrix.chunk }} \
            --repos-jsonl data/chunk_${{ matrix.chunk }}.jsonl \
            --output results/gha_chunk_${{ matrix.chunk }}.jsonl \
            --use-pyenv

      # ── 결과 업로드 ────────────────────────────────────────
      - name: Upload results artifact
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: gha-results-chunk-${{ matrix.chunk }}
          path: |
            results/gha_chunk_${{ matrix.chunk }}.jsonl
            scripts_out/gha_chunk_${{ matrix.chunk }}/
```

### 5-2. pyright 평가 스크립트

`scripts/gha_evaluate.py`:

```python
#!/usr/bin/env python3
"""
GHA 환경에서 bootstrap script를 실행하고 pyright로 평가한다.
Docker의 python_build.sh와 동일한 로직을 재현한다.
"""
import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def run_bootstrap_and_evaluate(
    repo_name: str,
    commit_sha: str,
    bootstrap_script: str,
    use_pyenv: bool = True,
) -> dict:
    """
    1. 레포 클론 (지정 commit)
    2. bootstrap_script 실행
    3. pyright --outputjson 실행
    4. issues_count 반환
    """
    result = {
        "repo_name": repo_name,
        "commit_sha": commit_sha,
        "exit_code": -1,
        "issues_count": 0,
        "execution_time": 0,
        "error": None,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Clone
        repo_url = f"https://github.com/{repo_name}.git"
        clone_cmd = ["git", "clone", "--depth=1", repo_url, tmpdir]
        if commit_sha:
            # shallow clone은 특정 commit을 직접 못 받으므로 fetch 방식 사용
            subprocess.run(["git", "init", tmpdir], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", tmpdir, "fetch", "--depth=1", repo_url, commit_sha],
                check=True, capture_output=True
            )
            subprocess.run(
                ["git", "-C", tmpdir, "checkout", "FETCH_HEAD"],
                check=True, capture_output=True
            )
        else:
            subprocess.run(clone_cmd, check=True, capture_output=True)

        # 2. bootstrap script 저장 및 실행
        bootstrap_path = os.path.join(tmpdir, "bootstrap_script.sh")
        with open(bootstrap_path, "w") as f:
            f.write(bootstrap_script)
        os.chmod(bootstrap_path, 0o755)

        start = time.time()
        try:
            proc = subprocess.run(
                ["bash", bootstrap_path],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=300,  # 5분 타임아웃
            )
            result["exit_code"] = proc.returncode
        except subprocess.TimeoutExpired:
            result["exit_code"] = 1
            result["error"] = "bootstrap_timeout"
            return result
        finally:
            result["execution_time"] = round(time.time() - start, 1)

        if result["exit_code"] != 0:
            return result

        # 3. pyright 평가 (Docker의 python_build.sh와 동일)
        pip_install = subprocess.run(
            ["python", "-m", "pip", "install", "--quiet", "pyright"],
            cwd=tmpdir, capture_output=True
        )

        pyright_proc = subprocess.run(
            ["python", "-m", "pyright", "--outputjson", "."],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )

        try:
            pyright_output = json.loads(pyright_proc.stdout)
            diagnostics = pyright_output.get("generalDiagnostics", [])
            # reportMissingImports만 카운트 (EnvBench 기준과 동일)
            missing_imports = [
                d for d in diagnostics
                if d.get("rule") == "reportMissingImports"
            ]
            result["issues_count"] = len(missing_imports)
        except (json.JSONDecodeError, KeyError):
            result["issues_count"] = 0

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scripts-dir", required=True)
    parser.add_argument("--repos-jsonl", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--use-pyenv", action="store_true")
    args = parser.parse_args()

    scripts_dir = Path(args.scripts_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(args.repos_jsonl) as f:
        repos = [json.loads(l) for l in f]

    # scripts.jsonl에서 bootstrap script 로드
    scripts_file = scripts_dir / "scripts.jsonl"
    scripts = {}
    if scripts_file.exists():
        with open(scripts_file) as f:
            for line in f:
                entry = json.loads(line)
                scripts[entry["repo_name"]] = entry.get("script", "")

    results = []
    for repo in repos:
        repo_name = repo["repo_name"]
        commit_sha = repo.get("commit_sha", "")
        bootstrap = scripts.get(repo_name, "")

        print(f"Evaluating {repo_name}...", flush=True)

        if not bootstrap:
            results.append({
                "repo_name": repo_name,
                "exit_code": -1,
                "issues_count": 0,
                "error": "no_bootstrap_script",
            })
            continue

        r = run_bootstrap_and_evaluate(repo_name, commit_sha, bootstrap, args.use_pyenv)
        results.append(r)
        print(f"  → exit_code={r['exit_code']}, issues={r['issues_count']}, time={r['execution_time']}s")

    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    total = len(results)
    passed = sum(1 for r in results if r.get("exit_code") == 0 and r.get("issues_count", 1) == 0)
    print(f"\nDone: {total} repos, pass@1={passed}/{total}={passed/total*100:.1f}%")


if __name__ == "__main__":
    main()
```

---

## 6. 결과 수집 및 비교 분석

### 6-1. GHA 결과 artifact 다운로드

GHA 워크플로우 완료 후:

```bash
# GitHub CLI로 artifact 다운로드
gh run download <RUN_ID> -D results/gha_raw/

# 청크 파일 병합
python3 - << 'EOF'
import json, glob

all_results = []
for chunk_file in sorted(glob.glob("results/gha_raw/gha-results-chunk-*/gha_chunk_*.jsonl")):
    with open(chunk_file) as f:
        for line in f:
            all_results.append(json.loads(line))

with open("results/gha_linux_results.jsonl", "w") as f:
    for r in all_results:
        f.write(json.dumps(r) + "\n")

print(f"Merged {len(all_results)} results → results/gha_linux_results.jsonl")
EOF
```

### 6-2. 두 환경 비교 분석

```python
# scripts/compare_docker_vs_gha.py
import json
import math

def load(path):
    with open(path) as f:
        return {json.loads(l)["repo_name"]: json.loads(l) for l in f}

docker = load("results/docker_baseline_sample50.jsonl")
gha = load("results/gha_linux_results.jsonl")

common = set(docker.keys()) & set(gha.keys())
print(f"Common repos: {len(common)}")

# ── 1. 전체 메트릭 비교 ──────────────────────────────────
def metrics(results_dict, repos):
    rs = [results_dict[r] for r in repos]
    total = len(rs)
    passed = sum(1 for r in rs if r.get("exit_code") == 0 and r.get("issues_count", 1) == 0)
    avg_err = sum(r.get("issues_count", 0) for r in rs) / total
    return {"n": total, "pass@1": passed/total*100, "avgErrs": avg_err}

docker_m = metrics(docker, common)
gha_m = metrics(gha, common)

print("\n=== Overall Metrics ===")
print(f"{'Method':<25} {'n':>4} {'pass@1':>8} {'avgErrs':>9}")
print("-" * 50)
print(f"{'Docker (EnvBench)':25} {docker_m['n']:>4} {docker_m['pass@1']:>7.1f}% {docker_m['avgErrs']:>9.2f}")
print(f"{'GHA ubuntu-22.04':25} {gha_m['n']:>4} {gha_m['pass@1']:>7.1f}% {gha_m['avgErrs']:>9.2f}")
delta_pass = gha_m['pass@1'] - docker_m['pass@1']
delta_err = gha_m['avgErrs'] - docker_m['avgErrs']
print(f"{'Delta':25} {'':>4} {delta_pass:>+7.1f}% {delta_err:>+9.2f}")

# ── 2. 레포별 일치율 (Cohen's Kappa) ─────────────────────
d_labels = [1 if docker[r].get("exit_code") == 0 and docker[r].get("issues_count", 1) == 0 else 0 for r in common]
g_labels = [1 if gha[r].get("exit_code") == 0 and gha[r].get("issues_count", 1) == 0 else 0 for r in common]

# Agreement
agree = sum(d == g for d, g in zip(d_labels, g_labels))
agreement_rate = agree / len(common)

# Cohen's Kappa
n = len(common)
p_o = agree / n  # observed agreement
p_e = (
    (sum(d_labels) / n) * (sum(g_labels) / n) +
    ((n - sum(d_labels)) / n) * ((n - sum(g_labels)) / n)
)  # expected agreement
kappa = (p_o - p_e) / (1 - p_e) if (1 - p_e) != 0 else 1.0

print(f"\n=== Agreement Analysis ===")
print(f"Per-repo agreement: {agree}/{len(common)} = {agreement_rate*100:.1f}%")
print(f"Cohen's Kappa: {kappa:.3f}")
print(f"  (≥0.80 = almost perfect, 0.60-0.80 = substantial, <0.60 = insufficient)")

# ── 3. 불일치 레포 분석 ─────────────────────────────────
disagreements = [r for r, d, g in zip(common, d_labels, g_labels) if d != g]
print(f"\n=== Disagreements ({len(disagreements)} repos) ===")
for repo in sorted(disagreements):
    dr = docker[repo]
    gr = gha[repo]
    print(f"  {repo}")
    print(f"    Docker: exit={dr.get('exit_code')}, issues={dr.get('issues_count')}")
    print(f"    GHA:    exit={gr.get('exit_code')}, issues={gr.get('issues_count')}")

# ── 4. issues_count 상관관계 ────────────────────────────
d_errors = [docker[r].get("issues_count", 0) for r in common]
g_errors = [gha[r].get("issues_count", 0) for r in common]

n = len(common)
mean_d = sum(d_errors) / n
mean_g = sum(g_errors) / n
cov = sum((d - mean_d) * (g - mean_g) for d, g in zip(d_errors, g_errors)) / n
std_d = math.sqrt(sum((d - mean_d)**2 for d in d_errors) / n)
std_g = math.sqrt(sum((g - mean_g)**2 for g in g_errors) / n)
pearson = cov / (std_d * std_g) if std_d * std_g > 0 else 0

print(f"\n=== Correlation (issues_count) ===")
print(f"Pearson r: {pearson:.3f}")
print(f"  (≥0.90 = high correlation → environments are equivalent)")

# ── 5. 결과 해석 ─────────────────────────────────────────
print("\n=== Conclusion ===")
if abs(delta_pass) <= 5.0 and kappa >= 0.75:
    print("✅ PASS: GHA ubuntu-22.04 results are EQUIVALENT to Docker baseline.")
    print("   → GHA-based evaluation is valid for cross-platform comparison.")
elif abs(delta_pass) <= 10.0 and kappa >= 0.60:
    print("⚠️  MARGINAL: Moderate agreement. Discuss as limitation in paper.")
    print("   → Report both numbers; use GHA Linux as reference for cross-platform.")
else:
    print("❌ FAIL: Significant divergence detected. Investigate differences.")
    print("   → Check pre-installed packages, Python version handling.")
```

```bash
python3 scripts/compare_docker_vs_gha.py
```

---

## 7. 실험 실행 순서 (전체 요약)

```bash
# ── Step 1: 샘플 준비 (로컬, ~5분) ─────────────────────────
cd /path/to/EnvAgent-multi

python3 scripts/sample_repos.py        # data/gha_validation_sample50.jsonl
python3 scripts/enrich_sample.py       # data/gha_validation_sample50_full.jsonl
python3 scripts/extract_docker_baseline.py  # results/docker_baseline_sample50.jsonl

# ── Step 2: git push (GHA 트리거용) ─────────────────────────
git add data/gha_validation_sample50_full.jsonl \
        .github/workflows/gha_linux_validation.yml \
        scripts/gha_evaluate.py
git commit -m "Add GHA Linux validation experiment"
git push

# ── Step 3: GHA 워크플로우 실행 ──────────────────────────────
gh workflow run gha_linux_validation.yml \
    -f repos_jsonl=data/gha_validation_sample50_full.jsonl \
    -f model=gpt-4o \
    -f max_iterations=30

# 실행 상태 모니터링
gh run list --workflow=gha_linux_validation.yml
gh run watch  # 실시간 로그

# ── Step 4: 결과 수집 ────────────────────────────────────────
# 완료 후 (약 2-4시간 예상, 5개 병렬 청크 × 10레포)
gh run download <RUN_ID> -D results/gha_raw/

python3 - << 'EOF'
import json, glob
all_results = []
for f_path in sorted(glob.glob("results/gha_raw/*/gha_chunk_*.jsonl")):
    with open(f_path) as f:
        all_results.extend(json.loads(l) for l in f)
with open("results/gha_linux_results.jsonl", "w") as f:
    for r in all_results:
        f.write(json.dumps(r) + "\n")
print(f"Merged {len(all_results)} results")
EOF

# ── Step 5: 비교 분석 ────────────────────────────────────────
python3 scripts/compare_docker_vs_gha.py
```

---

## 8. 결과 해석 기준 및 논문 서술 방법

### 판정 기준

| pass@1 차이 | Cohen's Kappa | Pearson r | 판정 | 논문 서술 |
|------------|--------------|-----------|------|---------|
| ≤ 5%p | ≥ 0.80 | ≥ 0.90 | ✅ 동등 | "GHA Linux results are equivalent to Docker" |
| ≤ 10%p | ≥ 0.60 | ≥ 0.75 | ⚠️ 보통 | "Minor environment differences noted (±Xpp), discussed in Threats to Validity" |
| > 10%p | < 0.60 | < 0.75 | ❌ 상이 | GHA 환경 조정 필요 (pyenv 설정 재검토) |

### 논문 내 서술 위치

**Section: Evaluation Framework** 또는 **Threats to Validity**

> To validate that our GHA-based evaluation framework produces results comparable to EnvBench's Docker-based approach, we ran the Bash Agent (GPT-4o) on a stratified sample of 50 repositories under both environments. The GHA ubuntu-22.04 results showed a pass@1 of X.X% versus X.X% in Docker (Δ=±X.Xpp), a per-repo agreement of X.X% (Cohen's κ=X.XX), and a Pearson correlation of r=X.XX for avgErrs. These results confirm that GHA Linux evaluation is [equivalent to / marginally different from] the Docker baseline, justifying its use as the Linux reference point for our cross-platform comparison.

---

## 9. 예상 비용 및 시간

| 항목 | 수량 | 단가 | 합계 |
|------|------|------|------|
| GHA ubuntu-22.04 (무료 tier) | 50 repos × ~10분 | 무료 | $0 |
| OpenAI API (gpt-4o) | 50 repos × ~$0.10 | $0.10/repo | ~$5 |
| **총합** | | | **~$5** |

> GHA Linux runner는 무료 tier(월 2,000분)로 충분히 처리 가능.
> gpt-4o-mini 사용 시 API 비용 ~$0.50으로 절감 가능 (단, 결과 품질 차이 있을 수 있음).

---

## 10. 트러블슈팅

### 에이전트가 scripts.jsonl을 생성하지 않는 경우

```bash
# EnvBench inference 로그 확인
cat EnvBench/outputs/python-bash/*/inference.log | tail -50

# scripts.jsonl 형식 확인
head -1 scripts_out/gha_chunk_0/scripts.jsonl | python3 -m json.tool
```

### pyright가 설치되지 않는 경우

```bash
# GHA runner에서 직접 테스트
pip install pyright
python -m pyright --version
```

### commit_sha로 클론 실패 (shallow fetch)

```bash
# 전체 clone으로 대체
git clone https://github.com/<repo>.git /tmp/test_repo
git -C /tmp/test_repo checkout <SHA>
```

### Docker 기준값과 repo_name 형식 불일치

```python
# results.jsonl의 repo_name 필드 확인
import json
with open("EnvBench-trajectories/python/bash_agent-4o/results.jsonl") as f:
    first = json.loads(f.readline())
print(first.keys())
print(first.get("repo_name"))  # "owner/repo" 형식인지 확인
```

---

*Last updated: 2026-03-16*
