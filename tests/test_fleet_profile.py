"""Fleet profile's trusted-host guard and offline vendor inventory gate."""
import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from fleet_profile_delta import before_fleet
from test_bean_counter_budget import selected
ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=(ROOT/'.github/workflows/compliance.yml').read_text()
class FleetProfileTests(unittest.TestCase):
 def test_exact_fleet_delta_and_pinned_historical_source(self):
  previous=before_fleet(WORKFLOW)
  self.assertEqual(hashlib.sha256(previous.encode()).hexdigest(), '7291f419cb81335fc553ebb64bc4a6c74cad80e6feb92c406a46a03ace6a7060')
  self.assertIn("inputs.repo == 'bean-fleet' && 'v0.7.11'",WORKFLOW)
  self.assertIn("inputs.repo == 'bean-fleet' || inputs.repo == 'agency'",WORKFLOW)
  self.assertIn('permission',WORKFLOW)
  self.assertNotIn('secrets.',WORKFLOW)
 def test_host_guard_denies_spoof_and_untrusted_runner(self):
  block=WORKFLOW.split('      - name: Guard fleet hosted-only profile',1)[1].split('      - name:',1)[0]
  shell=block.split('        run: |\n',1)[1]
  shell='\n'.join(line[10:] for line in shell.splitlines())
  env=dict(os.environ,GATE_REPO='stevekkall-beansgc/bean-fleet',GATE_RUNNER='macos-15',GATE_FULL='true',GATE_EVENT='push',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='macOS')
  self.assertEqual(subprocess.run(['bash','-c',shell],env=env).returncode,0)
  for key,value in (('RUNNER_ENVIRONMENT','self-hosted'),('RUNNER_OS','Linux'),('GATE_RUNNER','beans-mac'),('GATE_EVENT','pull_request_target'),('GATE_FULL','false')):
   bad=dict(env,**{key:value});self.assertNotEqual(subprocess.run(['bash','-c',shell],env=bad).returncode,0,key)
 def test_vendor_verifier_rejects_changes(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);caller=root/'caller';release=caller/'release';vendor=caller/'vendor/bean-commons';release.mkdir(parents=True);vendor.mkdir(parents=True)
   (vendor/'sample').write_text('fixture');sha=hashlib.sha256(b'fixture').hexdigest()
   manifest=json.dumps({'commit':'e1ca435f2d64bf694f4d81b6828dfff537e8afef','files':{'sample':sha}}).encode();requirements=b'fixture-public-lock'
   (release/'VENDORED-COMMONS.json').write_bytes(manifest);(release/'build-requirements.txt').write_bytes(requirements)
   block=WORKFLOW.split("          python3 - <<'PYCODE'\n",1)[1].split('          PYCODE\n',1)[0]
   script='\n'.join(line[10:] for line in block.splitlines())
   script=script.replace('7fa61859d3a7c032555c921f5e16c1ba9ecd58adb93316c22eb2fed97795b524',hashlib.sha256(manifest).hexdigest()).replace('6f8869592f6bb6e788c4d82813d4c7a3f2cb3f630a8715345174fdb37e0142c0',hashlib.sha256(requirements).hexdigest())
   def run():return subprocess.run([sys.executable,'-c',script],cwd=root,capture_output=True).returncode
   self.assertEqual(run(),0);(vendor/'sample').write_text('changed');self.assertNotEqual(run(),0)
   (vendor/'sample').write_text('fixture');(vendor/'extra').symlink_to(vendor/'sample');self.assertNotEqual(run(),0)
if __name__=='__main__':unittest.main()
