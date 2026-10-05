from pathlib import Path
import argparse, importlib.util
root=Path('/workspace/solana-wallet-scanner')
spec=importlib.util.spec_from_file_location('browser_mechanics',root/'tools/screening_browser.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
source=(root/'tools/screening_browser.py').read_text()
source=source.replace("page.get_by_text('Import a public candidate list',exact=True).click()", "page.get_by_role('button',name='Paste public wallets',exact=True).click()\n        assert page.locator('#candidate-import-addresses').evaluate('el => el === document.activeElement')\n        assert not page.locator('details.discovery-optional-provider').evaluate('el => el.open')")
source=source.replace("    for name,value in (('Simulated capital (SOL)'", "    page.get_by_role('button',name='Set up paper observation',exact=True).click()\n    expect(page.get_by_text('Start forward quote-based paper observation',exact=True)).to_be_in_viewport()\n    for name,value in (('Simulated capital (SOL)'")
source=source.replace("    assert initial['settings']['reaction_delay_seconds']==1", "    expect(page.get_by_text('Saved paper observations',exact=True)).to_be_in_viewport()\n    assert initial['settings']['reaction_delay_seconds']==1")
exec(compile(source,str(root/'tools/screening_browser.py'),'exec'),b.__dict__)
raise SystemExit(b.run(argparse.Namespace(output=root/'evidence/screening-forward-research/frontend-frozen-workflow-20261004',chromium='/usr/bin/chromium')))
