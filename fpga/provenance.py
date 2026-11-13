"""Ferrandi source/build evidence; hardware generation is independent of MDPI.

A remote URL is source-origin evidence only. A binary link requires either a
matching unambiguous revision banner, or a hash-checked build/install receipt.
Normal host runtime does not need the source checkout.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def banner_revision(output):
    m=re.search(r'\bRevision\s+([0-9a-fA-F]{7,40})(?=[^0-9a-fA-F]|$)',output)
    return m[1].lower() if m else None


def verify_bambu(binary,source=None,receipt=None,require_ramulator=False):
    config=json.loads((ROOT/'fpga/toolchain.json').read_text())
    allowed={config['bambu']['revision']} if require_ramulator else set(config['hardware_accepted_revisions'])
    resolved=Path(shutil.which(binary) or binary).resolve()
    p=subprocess.run([str(resolved),'--version'],capture_output=True,text=True,timeout=20)
    output=p.stdout+p.stderr
    if p.returncode:raise ValueError('Bambu --version failed: '+output[-2000:])
    binary_sha=sha(resolved);token=banner_revision(output)
    receipt=receipt or os.environ.get('FPGA_TOOLCHAIN_RECEIPT')
    if receipt:
        path=Path(receipt);r=json.loads(path.read_text())
        if r.get('repository')!='ferrandi/PandA-bambu' or r.get('source_revision') not in allowed:
            raise ValueError('Receipt does not select an accepted Ferrandi revision for this mode')
        if r.get('binary_sha256')!=binary_sha:raise ValueError('Bambu binary changed since build receipt')
        if not r.get('build_evidence') or 'REPLACE' in str(r.get('build_evidence')) or not r.get('artifacts'):raise ValueError('Receipt must link source/build evidence and installed runtime artifact hashes')
        for relative,fingerprint in r['artifacts'].items():
            name=Path(relative)
            if name.is_absolute() or '..' in name.parts:raise ValueError('Receipt artifacts must be relative to installation prefix')
            prefix=Path(os.environ.get('BAMBU_HLS',str(resolved.parent.parent)))
            if sha(prefix/name)!=fingerprint:raise ValueError('Installed runtime fingerprint changed: '+relative)
        if token and not r['source_revision'].startswith(token):raise ValueError('Banner and receipt revision disagree')
        return dict(repository=r['repository'],revision=r['source_revision'],binary=str(resolved),binary_sha256=binary_sha,
                    version=output,banner_revision=token,evidence='hash-checked build/install receipt',receipt_sha256=sha(path),
                    ramulator_capability=require_ramulator or r['source_revision']==config['bambu']['revision'])
    source=source or os.environ.get('FPGA_BAMBU_SOURCE')
    if not source:raise ValueError('Set FPGA_TOOLCHAIN_RECEIPT (installed artifact manifest) or FPGA_BAMBU_SOURCE; no Jesun fallback. Hardware does not require Ramulator capability.')
    def git(*args):return subprocess.check_output(['git','-C',str(source),*args],text=True,stderr=subprocess.STDOUT).strip()
    revision=git('rev-parse','HEAD');remotes=git('remote','-v')
    if not re.search(r'github.com[:/]ferrandi/PandA-bambu(?:\.git)?(?:\s|$)',remotes):raise ValueError('Checkout is not linked to Ferrandi/PandA-bambu; URL alone would not verify the binary')
    if revision not in allowed:raise ValueError('Unreviewed Ferrandi revision for this execution mode: '+revision+'; recorded choices in fpga/toolchain.json')
    if git('status','--porcelain','--untracked-files=no'):raise ValueError('Tracked Ferrandi source changes need an explicit build/install receipt')
    if not token or not revision.startswith(token):raise ValueError('Binary/source link unresolved: matching revision banner or build receipt required; full SHA is not required in banner')
    # Git resolves abbreviated IDs only when unambiguous in this checkout.
    if git('rev-parse','--verify',token+'^{commit}')!=revision:raise ValueError('Ambiguous/mismatched abbreviated binary revision')
    return dict(repository='ferrandi/PandA-bambu',revision=revision,binary=str(resolved),binary_sha256=binary_sha,
                version=output,banner_revision=token,source=str(Path(source).resolve()),
                evidence='clean source plus unambiguous revision banner',runtime_link='not independently verified without an installed-artifact receipt',
                ramulator_capability=revision==config['bambu']['revision'])
