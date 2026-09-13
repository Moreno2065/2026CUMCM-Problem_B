import hashlib, json, base64

A = r'D:\CUMCM2026\simu\数据\formal-p3-1-VUXH-728S-5QND-4JGQ.jlog'
B = r'D:/CUMCM2026/agentworkspace/out/support_stage/05_simulator_logs/formal-p3-1.jlog'
a = open(A,'rb').read(); b = open(B,'rb').read()
oa = json.loads(a[14:3230].decode()); ob = json.loads(b[14:3230].decode())
def ud(s): return base64.urlsafe_b64decode(s + '='*(-len(s)%4))
ra, rb = ud(oa['server_ticket_b64']), ud(ob['server_ticket_b64'])

print("=== ACCOUNTING ===")
blob_changed = [i for i in range(1010) if ra[i]!=rb[i]]
mangle = [i for i in blob_changed if ra[i]>=0x80 and rb[i]==0x3F]
team   = [i for i in blob_changed if 82<=i<=93]
print("blob bytes changed:", len(blob_changed), " = mangle(high->0x3F):", len(mangle), "+ team_no:", len(team))
print("mangle offsets:", mangle)
print("team_no offsets:", team)
print("outer team_no changed bytes:", 8, "-> total 8+33 = 41 blob bytes")
print()
print("length prefix A:", ra[8:14].hex(' '), "->", int.from_bytes(ra[10:14],'big'))
print("length prefix B:", rb[8:14].hex(' '), "->", int.from_bytes(rb[10:14],'big'), "(0xA4 -> 0x3F inside the 4-byte BE length)")
print("actual inner JSON bytes present:", 932, " declared in B:", 831, " delta:", 932-831)
print()
print("=== ticket inner JSON in B: parse test ===")
try:
    json.loads(rb[14:14+831].decode()); print("  parses")
except Exception as e: print("  json.loads(rb[14:14+831]) -> FAIL:", e)
print()
print("=== signature region: A blob 946..1010 vs B ===")
print("off  A  B   | base64 chars covering blob byte offset")
print("A sig hex:", ra[946:].hex(' '))
print("B sig hex:", rb[946:].hex(' '))
print("identical bytes in sig:", sum(1 for i in range(64) if ra[946+i]==rb[946+i]), "/64")
print("sig bytes destroyed:", sum(1 for i in range(64) if ra[946+i]>=0x80), "/64")
print()
# worked base64 example
for blk in ((0x3f,0x3f,0x3f), (0x8f,0xcf,0x3f)):
    print(f"  bytes {bytes(blk).hex(' ')} -> urlsafe_b64 {base64.urlsafe_b64encode(bytes(blk)).decode()}")
print("  A sig local  f4 a1 3f ->", base64.urlsafe_b64encode(ra[946+2:946+5]).decode())
print("  B sig local  3f 3f 3f ->", base64.urlsafe_b64encode(rb[946+2:946+5]).decode())
print()
print("=== alphabet proof ===")
for nm, s in (('ticket A', oa['server_ticket_b64']), ('ticket B', ob['server_ticket_b64']),
              ('wrapped_dek A', oa['wrapped_deks'][0]['wrapped_dek_b64']),
              ('nonce_prefix A', oa['nonce_prefix_b64'])):
    print(f"  {nm}: '-'={s.count('-')} '_'={s.count('_')} '+'={s.count('+')} '/'={s.count('/')}")
print("  -> URL-safe alphabet (RFC4648 s5) used in BOTH files; no '/' anywhere; '+' never used.")
print()
print("=== sha256 of regions ===")
for nm, buf in (('A envelope', a[14:3230]), ('B envelope', b[14:3230]),
                ('A frames', a[3230:101512]), ('B frames', b[3230:101512]),
                ('A trailer', a[101512:]), ('B trailer', b[101512:])):
    print(f"  {nm}: {hashlib.sha256(buf).hexdigest()}")
print()
print("=== other integrity-relevant fields (identical?) ===")
for k in ('build_id','build_manifest_sha256','package_signing_public_key_b64','created_at_utc','case_code','nonce_prefix_b64'):
    print(f"  outer {k}: identical={oa[k]==ob[k]}  value={oa[k]}")
tj = json.loads(ra[14:946].decode())
print("  ticket signing_key_id:", tj['signing_key_id'], "| ticket team_no:", tj['team_no'])
print("  ticket issued_at:", tj['issued_at'], "| activated_at:", tj['activated_at'])
print("  ticket case_unlock_envelope_sha256:", tj['case_unlock_envelope_sha256'])
print("  ticket sealed_case_package_sha256:", tj['sealed_case_package_sha256'])
print("  ticket device_digest:", tj['device_digest'])
