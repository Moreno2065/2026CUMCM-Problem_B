import hashlib, json, base64

A = r'D:\CUMCM2026\simu\数据\formal-p3-1-VUXH-728S-5QND-4JGQ.jlog'
B = r'D:/CUMCM2026/agentworkspace/out/support_stage/05_simulator_logs/formal-p3-1.jlog'
a = open(A,'rb').read(); b = open(B,'rb').read()
ea = a[14:3230].decode(); eb = b[14:3230].decode()
oa = json.loads(ea); ob = json.loads(eb)
def ud(s): return base64.urlsafe_b64decode(s + '='*(-len(s)%4))
ra, rb = ud(oa['server_ticket_b64']), ud(ob['server_ticket_b64'])

def hexdump(buf, base=0, width=16):
    out=[]
    for i in range(0, len(buf), width):
        chunk = buf[i:i+width]
        hx = ' '.join(f'{c:02X}' for c in chunk)
        asc = ''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)
        out.append(f"{base+i:6d}  {hx:<47}  |{asc}|")
    return '\n'.join(out)

print("###################### STRUCTURE ######################")
print("magic          : 0..8    ", a[0:8])
print("version/flags  : 8..10   ", a[8:10].hex(' '))
print("json len (4B BE): 10..14 ", a[10:14].hex(' '), "=", int.from_bytes(a[10:14],'big'))
L = int.from_bytes(a[10:14],'big')
print("JSON envelope  : 14..%d  (declared %d, actual %d)" % (14+L, L, L))
print("  envelope ends with:", repr(a[14+L-1:14+L]), " next byte:", a[14+L:14+L+1].hex())
print("binary tail    : %d..%d (%d bytes)" % (14+L, len(a), len(a)-(14+L)))
t = 14+L
print("  frame header : idx=%d plaintext_len=%d ciphertext_len=%d" % (
    int.from_bytes(a[t:t+4],'big'), int.from_bytes(a[t+4:t+8],'big'), int.from_bytes(a[t+8:t+12],'big')))
pl = int.from_bytes(a[t+4:t+8],'big'); cl = int.from_bytes(a[t+8:t+12],'big')
print("  ciphertext+tag:", t+12, "..", t+12+cl, "   (cl == pl+16 ?", cl == pl+16, ")")
print("  64-byte trailer:", t+12+cl, "..", len(a), " = file end?", t+12+cl+64 == len(a))
print("  trailer sha256:", hashlib.sha256(a[t+12+cl:]).hexdigest())
print("  trailer hex:", a[t+12+cl:].hex(' '))
print("  frame region identical A/B:", a[t:t+12+cl] == b[t:t+12+cl])
print("  trailer identical A/B:", a[t+12+cl:] == b[t+12+cl:])
print("  nonce_prefix_b64 ->", ud(oa['nonce_prefix_b64']).hex(' '))
print()
print("base64 vs binary in envelope region: all bytes <128 ?",
      all(c < 128 for c in a[14:14+L]))
print("binary tail high-bit count:", sum(1 for c in a[t:] if c > 127), " 0x3F count:", a[t:].count(0x3F))
print()

print("###################### DIFF REGIONS ######################")
diffs = [i for i in range(len(a)) if a[i]!=b[i]]
runs=[]; cur=[diffs[0]]
for x in diffs[1:]:
    if x==cur[-1]+1: cur.append(x)
    else: runs.append(cur); cur=[x]
runs.append(cur)
for r in runs:
    lo, hi = r[0], r[-1]
    s = max(0, lo-8); e = min(len(a), hi+9)
    print(f"--- run {lo}..{hi} ({len(r)} byte(s)) ---")
    print("A:", ' '.join(f'{c:02X}' for c in a[lo:hi+1]), " | ascii:", ''.join(chr(c) if 32<=c<127 else '.' for c in a[lo:hi+1]))
    print("B:", ' '.join(f'{c:02X}' for c in b[lo:hi+1]), " | ascii:", ''.join(chr(c) if 32<=c<127 else '.' for c in b[lo:hi+1]))
print()

print("###################### hexdump 120..150 (team_no) ######################")
print("FILE A"); print(hexdump(a[120:150],120))
print("FILE B"); print(hexdump(b[120:150],120))
print()
print("A team_no value bytes 130..142:", a[130:142].decode())
print("B team_no value bytes 130..142:", b[130:142].decode())
print()
print("###################### hexdump 460..600 (ticket head) ######################")
print("FILE A"); print(hexdump(a[460:600],460))
print("FILE B"); print(hexdump(b[460:600],460))
print()
print("###################### hexdump 1700..1815 ######################")
print("FILE A"); print(hexdump(a[1700:1815],1700))
print("FILE B"); print(hexdump(b[1700:1815],1700))
print()
