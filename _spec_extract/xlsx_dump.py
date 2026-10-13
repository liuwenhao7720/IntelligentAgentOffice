import zipfile, sys, re
import xml.etree.ElementTree as ET

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def col_to_idx(ref):
    letters = ''.join(c for c in ref if c.isalpha())
    n = 0
    for c in letters:
        n = n * 26 + (ord(c.upper()) - 64)
    return n - 1

def dump(path):
    z = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in root.findall('m:si', NS):
            text = ''.join(t.text or '' for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'))
            shared.append(text)
    # workbook sheet order
    wbroot = ET.fromstring(z.read('xl/workbook.xml'))
    relroot = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    relmap = {r.get('Id'): r.get('Target') for r in relroot}
    RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
    for sh in wbroot.find('m:sheets', NS):
        name = sh.get('name')
        target = relmap.get(sh.get(RNS), '')
        spath = 'xl/' + target.lstrip('/') if not target.startswith('xl/') else target
        if spath not in z.namelist():
            spath = 'xl/worksheets/' + target.split('/')[-1]
        print(f"### SHEET: {name}")
        sroot = ET.fromstring(z.read(spath))
        count = 0
        for row in sroot.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
            cells = {}
            maxc = 0
            for c in row.findall('m:c', NS):
                ref = c.get('r', 'A1')
                idx = col_to_idx(ref)
                maxc = max(maxc, idx)
                t = c.get('t')
                v = c.find('m:v', NS)
                is_el = c.find('m:is', NS)
                if t == 's' and v is not None:
                    val = shared[int(v.text)]
                elif t == 'inlineStr' and is_el is not None:
                    val = ''.join(x.text or '' for x in is_el.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'))
                elif v is not None:
                    val = v.text or ''
                else:
                    val = ''
                cells[idx] = val
            line = ' | '.join(cells.get(i, '') for i in range(maxc + 1)).rstrip(' |')
            if line.strip():
                print(line)
                count += 1
            if count > 800:
                print('...TRUNCATED...')
                break

dump(sys.argv[1])
