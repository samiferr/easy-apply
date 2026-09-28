import struct

def parse_po(file_path):
    catalog = {}
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    current_id = None
    current_str = None
    state = None  # 'id' or 'str'

    def unescape(s):
        # strip outer quotes
        s = s.strip()
        if s.startswith('"') and s.endswith('"'):
            s = s[1:-1]
        res = []
        i = 0
        n = len(s)
        while i < n:
            if s[i] == '\\' and i + 1 < n:
                nxt = s[i+1]
                if nxt == 'n':
                    res.append('\n')
                elif nxt == 't':
                    res.append('\t')
                elif nxt == '"':
                    res.append('"')
                elif nxt == '\\':
                    res.append('\\')
                else:
                    res.append(nxt)
                i += 2
            else:
                res.append(s[i])
                i += 1
        return ''.join(res)

    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.startswith('#'):
            continue

        if line_clean.startswith('msgid '):
            if current_id is not None and current_str is not None:
                catalog[current_id] = current_str
            current_id = unescape(line_clean[6:])
            current_str = None
            state = 'id'
        elif line_clean.startswith('msgstr '):
            current_str = unescape(line_clean[7:])
            state = 'str'
        elif line_clean.startswith('"'):
            if state == 'id' and current_id is not None:
                current_id += unescape(line_clean)
            elif state == 'str' and current_str is not None:
                current_str += unescape(line_clean)

    if current_id is not None and current_str is not None:
        catalog[current_id] = current_str

    return catalog

def write_mo(catalog, mo_file):
    keys = sorted(catalog.keys())
    num_strings = len(keys)

    orig_table_offset = 28
    trans_table_offset = 28 + 8 * num_strings
    data_offset = trans_table_offset + 8 * num_strings

    orig_entries = []
    trans_entries = []
    data = bytearray()

    for k in keys:
        b_k = k.encode('utf-8') + b'\x00'
        orig_entries.append((len(b_k) - 1, data_offset + len(data)))
        data.extend(b_k)

    for k in keys:
        b_v = catalog[k].encode('utf-8') + b'\x00'
        trans_entries.append((len(b_v) - 1, data_offset + len(data)))
        data.extend(b_v)

    mo = bytearray()
    mo.extend(struct.pack('Iiiiiii',
        0x950412de, 0, num_strings,
        orig_table_offset, trans_table_offset,
        0, 0
    ))

    for length, offset in orig_entries:
        mo.extend(struct.pack('ii', length, offset))
    for length, offset in trans_entries:
        mo.extend(struct.pack('ii', length, offset))

    mo.extend(data)

    with open(mo_file, 'wb') as f:
        f.write(mo)

    print(f"Successfully compiled {num_strings} messages to {mo_file}")

if __name__ == '__main__':
    cat = parse_po('locale/fr/LC_MESSAGES/django.po')
    print("Empty key (metadata) present?", '' in cat)
    if '' in cat:
        for line in cat[''].split('\n')[:5]:
            print("  ", line)
    write_mo(cat, 'locale/fr/LC_MESSAGES/django.mo')
