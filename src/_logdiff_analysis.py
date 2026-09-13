import hashlib, json, base64, itertools
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

A = r'D:\CUMCM2026\simu\数据\formal-p3-1-VUXH-728S-5QND-4JGQ.jlog'
B = r'D:/CUMCM2026/agentworkspace/out/support_stage/05_simulator_logs/formal-p3-1.jlog'
a = open(A,'rb').read(); b = open(B,'rb').read()
oa = json.loads(a[14:3230].decode()); ob = json.loads(b[14:3230].decode())

def ud(s): return base64.urlsafe_b64decode(s + '='*(-len(s)%4))
print("nonce_prefix_b64 ->", ud(oa['nonce_prefix_b64']).hex(' '), "len", len(ud(oa['nonce_prefix_b64'])))
print("package_signing_public_key_b64 ->", ud(oa['package_signing_public_key_b64']).hex(' '), "len", len(ud(oa['package_signing_public_key_b64'])))
print("wrapped_dek lens:", [len(ud(d['wrapped_dek_b64'])) for d in oa['wrapped_deks']])
print()

# ---- ticket internals ----
ra, rb = ud(oa['server_ticket_b64']), ud(ob['server_ticket_b64'])
la = int.from_bytes(ra[10:14],'big'); lb = int.from_bytes(rb[10:14],'big')
ja, jb = ra[14:14+la], rb[14:14+lb]
tj = json.loads(ja.decode())
print("ticket JSON keys:", list(tj.keys()))
for k in ('case_unlock_public_key_b64','package_signing_public_key_b64'):
    print(f"  {k} -> len {len(ud(tj[k]))} bytes")
print("ticket inner JSON len:", len(ja), "ticket total blob:", len(ra))
print()

pkpkg = Ed25519PublicKey.from_public_bytes(ud(oa['package_signing_public_key_b64']))
pkunlock = Ed25519PublicKey.from_public_bytes(ud(tj['case_unlock_public_key_b64']))

def try_verify(pk, sig, msg, label):
    try:
        pk.verify(sig, msg)
        print(f"  VERIFY OK   {label}")
        return True
    except InvalidSignature:
        return False

print("### A: ticket signature candidates (64-byte tail of ticket blob) ###")
siga = ra[946:]
cands = {
 'inner JSON raw (932B)': ja,
 'magic+ver+len+JSON': ra[:14+la],
 'sha256(inner JSON)': hashlib.sha256(ja).digest(),
}
for name, msg in cands.items():
    for kn, pk in (('package_signing_pub', pkpkg), ('case_unlock_pub', pkunlock)):
        try_verify(pk, siga, msg, f"{name} with {kn}")
print()

# ---- file trailer ----
trailer_a = a[-64:]; trailer_b = b[-64:]
frames = a[3230:101512]
print("### A: file trailer (last 64B) candidates ###")
msgs = {
 'envelope only (14:3230)': a[14:3230],
 'frames (3230:101512)': frames,
 'envelope+frames (14:101512)': a[14:101512],
 'file minus trailer (0:101512)': a[:101512],
 'whole file (0:101576)': a,
 'sha256(envelope)': hashlib.sha256(a[14:3230]).digest(),
 'sha256(frames)': hashlib.sha256(frames).digest(),
 'sha256(envelope+frames)': hashlib.sha256(a[14:101512]).digest(),
 'sha256(file minus trailer)': hashlib.sha256(a[:101512]).digest(),
}
hit = None
for name, msg in msgs.items():
    if try_verify(pkpkg, trailer_a, msg, name): hit = name
if hit is None: print("  (no candidate verified with package_signing_public_key)")
