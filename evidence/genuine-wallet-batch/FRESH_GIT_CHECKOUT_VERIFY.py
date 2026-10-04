from pathlib import Path,PurePosixPath
import base64,gzip,hashlib,importlib.util,json,os,shutil,stat,subprocess,tempfile,zipfile
from datetime import datetime,timezone
repo=Path.cwd()
commit='7f87d3eaba4beea793835e586836d22210b91b6d'
receipt_path=repo/'evidence/genuine-wallet-batch/FRESH_GIT_CHECKOUT_VERIFIED.json'
expected=json.loads((repo/'evidence/genuine-wallet-batch/SOURCE_MANIFEST.json').read_bytes())
scratch=Path(tempfile.mkdtemp(prefix='fresh-git-7f87d3e-',dir='/workspace/outputs'))
scratch.rmdir()
commands=[]
def cmd(args,cwd=repo):
    result=subprocess.run(args,cwd=cwd,capture_output=True,text=True)
    commands.append({'argv':args,'cwd':str(cwd),'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    if result.returncode:
        raise RuntimeError(f'Command failed: {args}')
    return result.stdout.strip()
def sha(body):return hashlib.sha256(body).hexdigest()
def file_binding(path,expected_sha=None):
    body=(scratch/path).read_bytes()
    binding={'path':path,'bytes':len(body),'sha256':sha(body),'matches_original_checkout':body==(repo/path).read_bytes()}
    if expected_sha is not None:
        binding['expected_sha256']=expected_sha
        binding['expected_hash_matches']=binding['sha256']==expected_sha
    assert binding['matches_original_checkout']
    assert expected_sha is None or binding['expected_hash_matches']
    return binding
record={'kind':'fresh-git-checkout-source-and-input-verification','created_at':datetime.now(timezone.utc).isoformat(),
        'application_commit':commit,'state':'INCOMPLETE','commands':commands,'scratch_path':str(scratch),
        'scope':'Evidence-only normal detached Git checkout, source byte/mode and immutable input verification. No application acceptance or provider execution.',
        'no_acceptance_rerun':True,'provider_requests':0,'credential_lookups':0,'PRODUCT_READY':False}
created=False
old_umask=os.umask(0o077)
record['checkout_umask']='0077'
record['previous_process_umask']=format(old_umask,'04o')
record['mode_scope']='POSIX checkout under inherited workspace0077umask. Git executable bits are preserved. This does not claim universal0644/0755 permission equality on other installations.'
record['verification_script_sha256']=sha(Path(__file__).read_bytes())
record['verification_command']=['python','evidence/genuine-wallet-batch/FRESH_GIT_CHECKOUT_VERIFY.py']
try:
    assert cmd(['git','rev-parse',commit])==commit
    cmd(['git','worktree','add','--detach',str(scratch),commit])
    created=True
    assert cmd(['git','rev-parse','HEAD'],scratch)==commit
    spec=importlib.util.spec_from_file_location('fresh_source_validation',scratch/'tools/validate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    actual=module.source_manifest(scratch)
    record.update(file_count=len(actual['files']),source_sha256=actual['sha256'],expected_source_sha256=expected['sha256'],
        byte_hashes_equal=actual['files']==expected['files'],modes_equal=actual['modes']==expected['modes'],source_manifest_equal=actual==expected,
        checkout_modes=actual['modes'])
    assert actual==expected
    frozen=json.loads((scratch/'evidence/genuine-wallet-batch/checker-inputs/FINAL_INPUT_FREEZE.json').read_bytes())
    archive=frozen['archive']
    record['archive_binding']=file_binding(archive,frozen['archive_sha256'])
    assert record['archive_binding']['bytes']==frozen['bytes']
    compact_oracle='evidence/genuine-wallet-batch/checker-inputs/FINAL_EXPECTED_RAW.json'
    record['compact_oracle_binding']=file_binding(compact_oracle,frozen['oracle_sha256'])
    reseal=json.loads((scratch/'evidence/genuine-wallet-batch/WORKED_REAL_RESEAL.json').read_bytes())
    oracle=reseal['final_expectations_path']
    record['oracle_binding']=file_binding(oracle,reseal['final_expectations_sha256'])
    record['calculator_binding']=file_binding(reseal['calculator_path'],reseal['calculator_sha256'])
    worked=json.loads((scratch/oracle).read_bytes())
    assert worked['archive_sha256']==frozen['archive_sha256']
    record['core_oracle_files']=[file_binding('evidence/genuine-wallet-batch/'+name) for name in
        ('WORKED_REAL_CALCULATOR.py','WORKED_REAL_EXPECTATIONS.json','WORKED_REAL_RESEAL.json','WORKED_REAL_RESEAL.log','SOURCE_AND_LEDGER_REVIEW.json')]
    extraction=scratch/'evidence/fresh-verification-extraction'
    with zipfile.ZipFile(scratch/archive) as z:
        bad=z.testzip()
        record['zip_integrity']={'state':'PASS' if bad is None else 'FAIL','first_bad_member':bad,'member_count':len(z.infolist())}
        assert bad is None
        names=z.namelist()
        assert len(names)==len(set(names))
        for info in z.infolist():
            path=PurePosixPath(info.filename)
            assert not path.is_absolute() and '..' not in path.parts and '\\' not in info.filename
            assert not stat.S_ISLNK(info.external_attr>>16)
        z.extractall(extraction)
        zipped_manifest=json.loads(z.read('manifest.json'))
        raw=[]
        for section in ('pages','transactions'):
            for link in zipped_manifest[section]:
                for kind in ('request','response'):
                    digest=link[kind+'_hash'];member='raw/'+digest+'.json'
                    original=z.read(member);extracted=(extraction/member).read_bytes()
                    assert sha(original)==digest and extracted==original
                    raw.append({'kind':section+'/'+kind,'member':member,'bytes':len(original),'sha256':digest,'extracted_hash':sha(extracted)})
        assert set(names)=={'manifest.json',*[row['member'] for row in raw]}
        record['fresh_zip_extraction']={'state':'PASS','raw_members':raw,'manifest_sha256':sha(z.read('manifest.json')),'all_member_hashes_equal':True}
        raw_map={row['sha256'] for row in raw}
    raw_collection=[]
    for phase in ('phase5','phase6'):
        for path in sorted((scratch/'evidence/genuine-wallet-batch/collection'/phase).glob('*')):
            if path.name.endswith('-request.json') or path.name.endswith('-response.raw.gz'):
                relative=path.relative_to(scratch).as_posix()
                binding=file_binding(relative)
                body=path.read_bytes()
                unpacked=gzip.decompress(body) if path.suffix=='.gz' else body
                binding.update(original_raw_bytes=len(unpacked),original_raw_sha256=sha(unpacked),included_in_final_indexed_archive=sha(unpacked) in raw_map)
                raw_collection.append(binding)
    record['original_raw_collection_files']=raw_collection
    bound={row['original_raw_sha256'] for row in raw_collection}
    assert raw_map<=bound
    page=next(row for row in raw_collection if row['original_raw_sha256']==worked['source_page_sha256'])
    assert page['original_raw_bytes']==worked['source_page_bytes']
    primary=[]
    for prefix,name in [('tests/fixtures/retained_protocol_funding','SOURCE_DOCUMENTS.json'),('tests/fixtures/retained_protocol_funding','NATIVE_QUOTE_SOURCE.json')]:
        provenance=json.loads((scratch/prefix/name).read_bytes())
        sources=provenance.get('documents',[provenance.get('document')])
        for source in sources:
            if source:
                primary.append(file_binding(prefix+'/'+source['path'],source['sha256']))
    getter=json.loads((scratch/'tests/fixtures/compiled_instructions/getter-schema.json').read_bytes())
    for ref in [getter['legacy_reference'],getter['parsed_reference'],*getter['references']]:
        primary.append(file_binding(ref['local_path'],ref['sha256']))
    review=json.loads((scratch/'evidence/genuine-wallet-batch/SOURCE_AND_LEDGER_REVIEW.json').read_bytes())
    for source in review['source_bindings']:
        if source['path'].startswith('evidence/'):
            primary.append(file_binding(source['path'],source['sha256']))
    record['primary_reference_bindings']=primary
    assert module.source_manifest(scratch)==expected
    record.update(source_unchanged_after_verification=True,state='PASS',genuine_input_available=True,
        initial_tar_limitation='Earlier failed tar mode comparison is retained in FRESH_TAR_EXTRACTION_INITIAL.json. This receipt verifies a normal Git checkout under the recorded0077umask; no per-file mode rewriting or source change occurred.')
except Exception as exc:
    import traceback
    record.update(state='FAIL',error=repr(exc),traceback=traceback.format_exc())
finally:
    os.umask(old_umask)
    if created:
        result=subprocess.run(['git','worktree','remove','--force',str(scratch)],cwd=repo,capture_output=True,text=True)
        commands.append({'argv':['git','worktree','remove','--force',str(scratch)],'cwd':str(repo),'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        record['new_scratch_worktree_removed']=result.returncode==0 and not scratch.exists()
    else:
        record['new_scratch_worktree_removed']=not scratch.exists()
    receipt_path.write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'state':record['state'],'source_sha256':record.get('source_sha256'),'file_count':record.get('file_count'),'byte_hashes_equal':record.get('byte_hashes_equal'),'modes_equal':record.get('modes_equal'),'zip':record.get('archive_binding'),'original_raw_inputs':len(record.get('original_raw_collection_files',[])),'primary_sources':len(record.get('primary_reference_bindings',[])),'scratch_removed':record['new_scratch_worktree_removed'],'error':record.get('error'),'receipt':str(receipt_path)}))
raise SystemExit(0 if record['state']=='PASS' else 1)
