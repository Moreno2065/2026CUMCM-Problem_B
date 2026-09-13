import hashlib, json, base64

A = r'D:\CUMCM2026\simu\数据\formal-p3-1-VUXH-728S-5QND-4JGQ.jlog'
B = r'D:/CUMCM2026/agentworkspace/out/support_stage/05_simulator_logs/formal-p3-1.jlog'
a = open(A,'rb').read(); b = open(B,'rb').read()
ea = a[14:3230].decode(); eb = b[14:3230].decode()
oa = json.loads(ea); ob = json.loads(eb)

def ud(s): return base64.urlsafe_b64decode(s + '='*(-len(s)%4))
def ue(x): return base64.urlsafe_b64encode(x).decode().rstrip('=')

OLD, NEW = '202612004018', '000000000000'
raw_a = ud(oa['server_ticket_b64'])

print("=== A ticket blob: high-byte structure ===")
hi = [i for i,c in enumerate(raw_a) if c >= 0x80]
print("high byte count:", len(hi), "first:", hi[:12], "last:", hi[-6:])
# are there valid utf-8 multibyte sequences?
txt_utf8 = raw_a.decode('utf-8', 'replace')
print("utf-8 decode len:", len(txt_utf8), "(blob len 1010) -> shrink:", 1010-len(txt_utf8))
print("U+FFFD count:", txt_utf8.count('\ufffd'))
print()

def pipeline(raw, old, new, mode):
    if mode == 'latin1_ascii':
        t = raw.decode('latin-1')
        t = t.replace(old, new)
        return t.encode('ascii', 'replace')
    if mode == 'utf8_ascii':
        t = raw.decode('utf-8', 'replace')
        t = t.replace(old, new)
        return t.encode('ascii', 'replace')
    if mode == 'utf8_utf8':
        t = raw.decode('utf-8', 'replace')
        t = t.replace(old, new)
        return t.encode('utf-8', 'replace')
    if mode == 'latin1_utf8':
        t = raw.decode('latin-1')
        t = t.replace(old, new)
        return t.encode('utf-8', 'replace')
    raise ValueError(mode)

print("=== repro attempts: rebuild B envelope from A ===")
for mode in ('latin1_ascii','utf8_ascii','utf8_utf8','latin1_utf8'):
    raw2 = pipeline(raw_a, OLD, NEW, mode)
    b64_2 = ue(raw2)
    env2 = ea.replace('"team_no":"%s"' % OLD, '"team_no":"%s"' % NEW)
    env2 = env2.replace(oa['server_ticket_b64'], b64_2)
    ok = (env2 == eb)
    print(f" mode={mode:12s} blob len={len(raw2)} b64 len={len(b64_2)} envelope matches B: {ok}")
    if not ok:
        for i in range(min(len(env2), len(eb))):
            if env2[i] != eb[i]:
                print(f"    first mismatch at env idx {i} (file offset {14+i}): repro={env2[i]!r} B={eb[i]!r}")
                break
        else:
            print("    lengths differ:", len(env2), len(eb))
    if ok:
        file2 = a[:14] + env2.encode() + a[3230:]
        print("   FULL FILE byte-identical to B:", file2 == b)
        print("   rebuilt sha256:", hashlib.sha256(file2).hexdigest())
        print("   B       sha256:", hashlib.sha256(b).hexdigest())
        print("   rebuilt ticket len prefix:", raw2[8:14].hex(' '), "=", int.from_bytes(raw2[10:14],'big'))
