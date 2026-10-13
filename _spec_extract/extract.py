import zipfile, sys, xml.etree.ElementTree as ET

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
WT = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'

def para_text(p):
    return ''.join((t.text or '') for t in p.iter(WT))

def docx_to_text(path):
    z = zipfile.ZipFile(path)
    xml = z.read('word/document.xml').decode('utf-8')
    root = ET.fromstring(xml)
    body = root.find('w:body', NS)
    out = []
    for el in body:
        tag = el.tag.split('}')[1]
        if tag == 'p':
            out.append(para_text(el))
        elif tag == 'tbl':
            for row in el.findall('w:tr', NS):
                cells = []
                for tc in row.findall('w:tc', NS):
                    ctext = ' '.join(para_text(p) for p in tc.findall('w:p', NS))
                    cells.append(ctext.strip())
                out.append(' | '.join(cells))
    return '\n'.join(out)

if __name__ == '__main__':
    text = docx_to_text(sys.argv[1])
    open(sys.argv[2], 'w', encoding='utf-8').write(text)
    print(sys.argv[2], len(text))
