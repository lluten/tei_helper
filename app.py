import os
import json
import uuid
import re
from copy import deepcopy
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from flask import Flask, render_template, request, Response, redirect, url_for, session, send_from_directory
from markupsafe import Markup, escape
from werkzeug.exceptions import RequestEntityTooLarge
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from lxml import etree
from bs4 import BeautifulSoup

app = Flask(__name__)

# --- CONFIGURATION ---
_dev_secret = 'tei_secret_key_dev_only'
app.secret_key = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY') or _dev_secret
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'))
TAGS_FILE = os.environ.get('TAGS_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tags.json'))
TEI_LAYOUT_FILE = os.environ.get('TEI_LAYOUT_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tei_layout_template.xml'))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Server-side sessions (avoid cookie size limit for doc_meta / imported_lines)
app.config['SESSION_TYPE'] = os.environ.get('SESSION_TYPE', 'filesystem')
app.config['SESSION_FILE_DIR'] = os.environ.get('SESSION_FILE_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'flask_session'
)
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
Session(app)

# Request body limit (DoS mitigation); 50 MB
_max_content = os.environ.get('MAX_CONTENT_LENGTH_MB', '50')
app.config['MAX_CONTENT_LENGTH'] = int(_max_content) * 1024 * 1024


@app.errorhandler(RequestEntityTooLarge)
def handle_413(e):
    return (
        'Request too large. Maximum upload size is {} MB.'.format(_max_content),
        413,
        {'Content-Type': 'text/plain; charset=utf-8'},
    )


# Rate limiting (DoS mitigation). Default 60/min; upload routes stricter.
_rate_default = os.environ.get('RATELIMIT_DEFAULT', '60 per minute')
_rate_upload = os.environ.get('RATELIMIT_UPLOAD', '15 per minute')
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_rate_default],
    default_limits_per_method=True,
    storage_uri=os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'),
)
limiter.init_app(app)

DEFAULT_TAGS = []

def load_tags():
    if not os.path.exists(TAGS_FILE): return DEFAULT_TAGS
    try:
        with open(TAGS_FILE, 'r') as f:
            tags = json.load(f)
            order = {'visual': 1, 'editorial': 2, 'semantic': 3, 'structural': 4}
            tags.sort(key=lambda x: (order.get(x.get('category'), 99), x.get('label')))
            return tags
    except: return DEFAULT_TAGS

def save_tags(tags):
    with open(TAGS_FILE, 'w') as f:
        json.dump(tags, f, indent=2)

TEI_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<?xml-model href="https://vault.tei-c.org/P5/current/xml/tei/custom/schema/relaxng/tei_all.rng" schematypens="http://relaxng.org/ns/structure/1.0" type="application/xml"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <!-- fileDesc: full bibliographic description of the electronic file -->
    <fileDesc>
      <titleStmt>
        <title>{title}</title>
        <author>{author}</author>
        <date>{date}</date>
        <respStmt>
          <resp>transcribed by</resp>
          <name>{transcriber}</name>
        </respStmt>
        <respStmt>
          <resp>validated by</resp>
          <name>TEI-edit</name>
        </respStmt>
      </titleStmt>
      <publicationStmt>
        <p>Transcribed using TEI-edit.</p>
      </publicationStmt>
      <sourceDesc>
        <msDesc>
          <msIdentifier>
            <country>{country}</country>
            <settlement>{settlement}</settlement>
            <repository>{repository}</repository>
            <idno>{idno}</idno>
          </msIdentifier>
          <physDesc>
            <objectDesc>
              <supportDesc>
                <support>
                  <material>{material}</material>
                  <objectType>{objectType}</objectType>
                  <dimensions></dimensions>
                </support>
              </supportDesc>
              <layoutDesc>
                <layout></layout>
              </layoutDesc>
            </objectDesc>
            {handDesc}
          </physDesc>
          <history>
            <origin></origin>
            <provenance></provenance>
          </history>
        </msDesc>
      </sourceDesc>
    </fileDesc>
    <!-- encodingDesc: relationship between the electronic text and the source(s) -->
    <encodingDesc>
      <projectDesc><p>Digital transcription of the source document.</p></projectDesc>
      <editorialDecl>
        <p>Capital and lowercase letters will be normalized.</p>
      </editorialDecl>
      <samplingDecl><p>Full transcription of the selected folio(s).</p></samplingDecl>
    </encodingDesc>
    <!-- profileDesc: bibliographic aspects of the text (language, occasion, people, setting). Hand definitions (handNote) are in physDesc above. -->
    <profileDesc>
      <langUsage><p>{language}</p></langUsage>
      <textDesc>
        <channel mode="w">written</channel>
      </textDesc>
    </profileDesc>
    <!-- revisionDesc: the file's revision history -->
    <revisionDesc>
      <change when="{date}">Initial transcription created.</change>
    </revisionDesc>
  </teiHeader>
  <text>
    <body>
      <div type="edition"></div>
    </body>
  </text>
</TEI>
"""

def _xml_escape(s):
    if not s:
        return ''
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')


def _set_hand_note_content(hand_note, description, ns_tei):
    """Set handNote text from description. No XML parsing of user content (avoids parse errors); lxml escapes on output."""
    if not description or not description.strip():
        return
    hand_note.text = description.strip()


def build_hand_desc_element(hands, fallback_hand_note=''):
    """Build TEI handDesc as an element tree (for safe insertion). hands: list of dicts (xml_id, scope, medium, scribe, locus, description)."""
    ns_tei = 'http://www.tei-c.org/ns/1.0'
    hand_desc = etree.Element(f'{{{ns_tei}}}handDesc')
    if hands:
        for h in hands:
            xml_id = (h.get('xml_id') or '').strip() or None
            scope = (h.get('scope') or '').strip() or None
            medium = (h.get('medium') or '').strip() or None
            scribe = (h.get('scribe') or '').strip() or None
            locus = (h.get('locus') or '').strip() or None
            description = (h.get('description') or '').strip()
            hand_note = etree.SubElement(hand_desc, f'{{{ns_tei}}}handNote')
            if xml_id:
                hand_note.set('{http://www.w3.org/XML/1998/namespace}id', xml_id)
            if scope:
                hand_note.set('scope', scope)
            if medium:
                hand_note.set('medium', medium)
            if scribe:
                hand_note.set('scribe', scribe)
            if locus:
                locus_el = etree.SubElement(hand_note, f'{{{ns_tei}}}locus')
                locus_el.text = locus or None
                locus_el.tail = description if description else None
            else:
                _set_hand_note_content(hand_note, description, ns_tei)
    else:
        if fallback_hand_note:
            hand_note = etree.SubElement(hand_desc, f'{{{ns_tei}}}handNote')
            hand_note.text = fallback_hand_note
    return hand_desc


def _extract_hands_from_tree(tree, ns):
    """Extract all handNote elements from TEI tree into list of dicts."""
    hands = []
    for hn in tree.xpath('//t:handDesc/t:handNote', namespaces=ns):
        h = {}
        if hn.get('{http://www.w3.org/XML/1998/namespace}id'):
            h['xml_id'] = hn.get('{http://www.w3.org/XML/1998/namespace}id')
        elif hn.get('xml:id'):
            h['xml_id'] = hn.get('xml:id')
        if hn.get('scope'):
            h['scope'] = hn.get('scope')
        if hn.get('medium'):
            h['medium'] = hn.get('medium')
        if hn.get('scribe'):
            h['scribe'] = hn.get('scribe')
        locus_el = hn.find('t:locus', namespaces=ns)
        if locus_el is not None and locus_el.text:
            h['locus'] = locus_el.text
        texts = []
        if hn.text:
            texts.append(hn.text)
        for child in hn:
            local = etree.QName(child).localname if child.tag else ''
            if local == 'locus':
                if 'locus' not in h and child.text:
                    h['locus'] = child.text
                if child.tail:
                    texts.append(child.tail)
            else:
                texts.append(etree.tostring(child, encoding='unicode', method='xml'))
                if child.tail:
                    texts.append(child.tail)
        h['description'] = ''.join(texts).strip() if texts else ''
        hands.append(h)
    return hands


def get_tei_template():
    """Load TEI header/body template: custom file if present, else built-in. Placeholders: title, author, date, transcriber, country, settlement, repository, idno, material, objectType, handDesc, language."""
    if os.path.isfile(TEI_LAYOUT_FILE):
        try:
            with open(TEI_LAYOUT_FILE, 'r', encoding='utf-8-sig') as f:
                return f.read()
        except Exception:
            pass
    return TEI_TEMPLATE


def _apply_tei_template_placeholders(xml_str, defaults):
    """Substitute {placeholder} in template without interpreting braces in values. Escapes text fields for XML. handDesc is NOT substituted here; use an empty element so the doc parses, then inject handDesc in export_tei."""
    text_placeholders = ['title', 'author', 'date', 'transcriber', 'country', 'settlement', 'repository', 'idno', 'material', 'objectType', 'language']
    out = xml_str
    for key in text_placeholders:
        val = defaults.get(key, '???')
        out = out.replace('{' + key + '}', _xml_escape(str(val)) if val else '')
    out = out.replace('{handDesc}', '<handDesc xmlns="http://www.tei-c.org/ns/1.0"></handDesc>')
    return out


def _build_tei_root_element(defaults, hand_desc_el):
    """Build TEI root element in code (no string parsing). Never raises XMLSyntaxError. defaults: title, author, date, transcriber, country, settlement, repository, idno, material, objectType, language. hand_desc_el: handDesc element from build_hand_desc_element."""
    ns = TEI_NS

    def t(tag, text=None, **attrs):
        el = etree.Element(f'{{{ns}}}{tag}')
        for k, v in attrs.items():
            if v is not None:
                el.set(k, str(v))
        if text is not None:
            el.text = _xml_escape(str(text)) if text else None
        return el

    def add(parent, tag, text=None, **attrs):
        el = t(tag, text=text, **attrs)
        parent.append(el)
        return el

    tei = etree.Element(f'{{{ns}}}TEI', nsmap={None: ns})
    header = add(tei, 'teiHeader')
    fd = add(header, 'fileDesc')
    ts = add(fd, 'titleStmt')
    add(ts, 'title', defaults.get('title') or '???')
    add(ts, 'author', defaults.get('author') or '???')
    add(ts, 'date', defaults.get('date') or '???')
    add(ts, 'respStmt')
    ts[-1].append(t('resp', 'transcribed by'))
    ts[-1].append(t('name', defaults.get('transcriber') or '???'))
    add(ts, 'respStmt')
    ts[-1].append(t('resp', 'validated by'))
    ts[-1].append(t('name', 'TEI-edit'))
    add(fd, 'publicationStmt').append(t('p', 'Transcribed using TEI-edit.'))
    sd = add(fd, 'sourceDesc')
    ms = add(sd, 'msDesc')
    mi = add(ms, 'msIdentifier')
    add(mi, 'country', defaults.get('country') or '???')
    add(mi, 'settlement', defaults.get('settlement') or '???')
    add(mi, 'repository', defaults.get('repository') or '???')
    add(mi, 'idno', defaults.get('idno') or '???')
    pd = add(ms, 'physDesc')
    od = add(pd, 'objectDesc')
    supd = add(od, 'supportDesc')
    sup = add(supd, 'support')
    add(sup, 'material', defaults.get('material') or '???')
    add(sup, 'objectType', defaults.get('objectType') or '???')
    add(sup, 'dimensions')
    add(od, 'layoutDesc').append(t('layout'))
    pd.append(hand_desc_el)
    hist = add(ms, 'history')
    add(hist, 'origin')
    add(hist, 'provenance')
    enc = add(header, 'encodingDesc')
    add(enc, 'projectDesc').append(t('p', 'Digital transcription of the source document.'))
    add(enc, 'editorialDecl').append(t('p', 'Capital and lowercase letters will be normalized.'))
    add(enc, 'samplingDecl').append(t('p', 'Full transcription of the selected folio(s).'))
    prof = add(header, 'profileDesc')
    add(prof, 'langUsage').append(t('p', defaults.get('language') or '???'))
    td = add(prof, 'textDesc')
    add(td, 'channel', None, mode='w').text = 'written'
    rev = add(header, 'revisionDesc')
    add(rev, 'change', 'Initial transcription created.', when=defaults.get('date') or '???')
    text_el = add(tei, 'text')
    body = add(text_el, 'body')
    add(body, 'div', None, type='edition')
    return tei

def _indent_xml_string(xml_str, indent_str='  '):
    """Indent XML by tracking tag depth. Does not require valid XML (no parse)."""
    xml_str = xml_str.strip()
    if not xml_str:
        return xml_str
    out = []
    depth = 0
    i = 0
    n = len(xml_str)
    while i < n:
        # Skip whitespace between tags
        if xml_str[i] in ' \t\n\r':
            i += 1
            continue
        if xml_str[i] != '<':
            # Text content: take until next <
            start = i
            while i < n and xml_str[i] != '<':
                i += 1
            text = xml_str[start:i].strip()
            if text:
                out.append(depth * indent_str + text)
            continue
        # We're at '<'
        start = i
        if i + 1 < n and xml_str[i + 1] == '?':
            # PI: <?...?>
            end = xml_str.find('?>', i) + 2
            if end <= i:
                end = n
            out.append(xml_str[start:end])
            i = end
            continue
        if i + 1 < n and xml_str[i + 1] == '!':
            # Comment: <!-- ... -->
            end = xml_str.find('-->', i) + 3
            if end <= i:
                end = n
            out.append(depth * indent_str + xml_str[start:end])
            i = end
            continue
        # Find end of tag
        j = i + 1
        while j < n and xml_str[j] != '>':
            if xml_str[j] in '"\'':
                q = xml_str[j]
                j += 1
                while j < n and xml_str[j] != q:
                    j += 1
                if j < n:
                    j += 1
            else:
                j += 1
        if j >= n:
            j = n
        tag = xml_str[start:j + 1]
        i = j + 1
        is_closing = tag.startswith('</')
        is_self_closing = tag.rstrip().endswith('/>')
        if is_closing or is_self_closing:
            depth = max(0, depth - 1)
        out.append(depth * indent_str + tag)
        if not is_closing and not is_self_closing:
            depth += 1
    return '\n'.join(out)

def _safe_layout_display(xml_str):
    """Escape only the sequence that would break the textarea, then mark safe for HTML so XML displays with indents."""
    if not xml_str:
        return Markup('')
    safe = xml_str.replace('</textarea>', '</tei' + 'xtarea>')
    return Markup(safe)

# --- PAGE HELPERS (multi-page session model) ---

def build_page_from_pagexml(filepath):
    """Build a page dict from a Transkribus PageXML file. Image is requested from Transkribus via
    proxy; if that fails (e.g. network/auth), the editor shows the upload-image fallback."""
    tree = etree.parse(filepath)
    img_url = ""
    raw_img_url = ""
    meta = tree.xpath('//*[local-name()="TranskribusMetadata"]')
    if meta:
        raw_img_url = (meta[0].get('imgUrl') or "").strip()
        if raw_img_url and (raw_img_url.startswith('http://') or raw_img_url.startswith('https://')):
            img_url = url_for('proxy_image', url=raw_img_url)
        else:
            img_url = raw_img_url or ""
    orig_w, orig_h = 0, 0
    page_el = tree.xpath('//*[local-name()="Page"]')
    if page_el:
        orig_w = int(page_el[0].get('imageWidth', 0))
        orig_h = int(page_el[0].get('imageHeight', 0))
    lines_data = []
    for i, node in enumerate(tree.xpath('//*[local-name()="TextLine"]')):
        t_node = node.xpath('.//*[local-name()="Unicode"]/text()')
        text = t_node[0] if t_node else ""
        c_node = node.xpath('.//*[local-name()="Coords"]')
        points = c_node[0].get('points') if c_node else ""
        lines_data.append({'id': i, 'text': text, 'points': points, 'html': ''})
    return {
        'file': filepath,
        'lines': lines_data,
        'html': None,
        'img_url': img_url,
        'orig_width': orig_w,
        'orig_height': orig_h,
        'image_src': raw_img_url,
        'import_type': 'transkribus',
    }


def _decode_xml_char_refs(s):
    """Decode &#xNNNN; and &#N; in string to actual characters."""
    s = re.sub(r'&#x([0-9A-Fa-f]+);', lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    return s


def _collapse_choice_abbr_expan(line_xml):
    """Replace <choice><abbr>...</abbr><expan>...</expan></choice> with editor span so TEI round-trips."""
    def repl(m):
        abbr_inner = m.group(1) or ''
        expan_inner = m.group(2) or ''
        abbr_decoded = _decode_xml_char_refs(abbr_inner)
        abbr_text = re.sub(r'<[^>]+>', '', abbr_decoded).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        expan_flat = re.sub(r'<[^>]+>', '', expan_inner)
        expan_text = expan_flat.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<span class="tei-tag tag-choice" data-tag="choice" data-attr-expan="{expan_text}">{abbr_text}</span>'
    return re.sub(
        r'<choice[^>]*>\s*<abbr[^>]*>(.*?)</abbr>\s*<expan[^>]*>(.*?)</expan>\s*</choice>',
        repl, line_xml, flags=re.DOTALL
    )


def build_page_from_tei(tree, filepath):
    """Build a page dict from a TEI tree (body lines only). Caller sets session['doc_meta']."""
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    body = tree.xpath('//t:body/t:div', namespaces=ns)
    if not body:
        body = tree.xpath('//t:body', namespaces=ns)
    lines_data = []
    if body:
        body_xml = etree.tostring(body[0], encoding='unicode')
        body_xml = re.sub(r'^<[^>]+>', '', body_xml)
        body_xml = re.sub(r'</[^>]+>$', '', body_xml)
        raw_lines = re.split(r'<lb[^>]*>', body_xml)

        def tag_replacer(match):
            tag = match.group(1)
            attrs = match.group(2)
            content = match.group(3)
            attr_str = ""
            for k, v in re.findall(r'(\w+)="([^"]*)"', attrs):
                attr_str += f' data-attr-{k}="{v}"'
            return f'<span class="tei-tag tag-{tag}" data-tag="{tag}"{attr_str}>{content}</span>'

        for i, line_content in enumerate(raw_lines):
            if not line_content.strip():
                continue
            line_content = _collapse_choice_abbr_expan(line_content)
            html_line = re.sub(r'<(\w+)([^>]*)>(.*?)</\1>', tag_replacer, line_content)
            html_line = html_line.replace('xmlns="http://www.tei-c.org/ns/1.0"', '')
            text_only = re.sub(r'<[^>]+>', '', line_content).strip()
            lines_data.append({
                'id': i,
                'text': text_only,
                'html': html_line.strip(),
                'points': '',
            })
    return {
        'file': filepath,
        'lines': lines_data,
        'html': None,
        'img_url': '',
        'orig_width': 0,
        'orig_height': 0,
        'image_src': '',
        'import_type': 'tei',
    }


def build_page_from_image(filepath):
    """Build a page dict from an image file (one empty line, no coords)."""
    orig_w, orig_h = 0, 0
    try:
        from PIL import Image
        with Image.open(filepath) as im:
            orig_w, orig_h = im.size[0], im.size[1]
    except Exception:
        pass
    filename = os.path.basename(filepath)
    img_url = url_for('send_upload', filename=filename)
    return {
        'file': filepath,
        'lines': [{'id': 0, 'text': '', 'html': '', 'points': ''}],
        'html': None,
        'img_url': img_url,
        'orig_width': orig_w,
        'orig_height': orig_h,
        'image_src': '',
        'import_type': 'image',
    }


@app.route('/favicon.ico')
def favicon():
    """Serve favicon so browser tab shows the app icon when opening the app."""
    return send_from_directory(
        app.static_folder, 'favicon.svg', mimetype='image/svg+xml'
    )


@app.route('/uploads/<path:filename>')
def send_upload(filename):
    """Serve uploaded files (e.g. images for image-only import)."""
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/', methods=['GET', 'POST'])
@limiter.limit(_rate_upload, methods=['POST'])
def index():
    if request.method == 'POST':
        import_type = request.form.get('import_type', 'transkribus')
        uploaded_files = request.files.getlist('file')
        if not uploaded_files or not uploaded_files[0].filename:
            return render_template('index.html', error='Please select at least one file.')
        pages = []
        session['doc_meta'] = session.get('doc_meta') or {}
        for uploaded_file in uploaded_files:
            if not uploaded_file.filename:
                continue
            filename = f"{uuid.uuid4()}_{uploaded_file.filename}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            uploaded_file.save(filepath)
            if import_type == 'image':
                page = build_page_from_image(filepath)
            elif import_type == 'tei':
                try:
                    tree = etree.parse(filepath)
                    root = tree.getroot()
                    if 'TEI' in root.tag or 'ns/1.0' in root.tag:
                        meta = {}
                        ns = {'t': 'http://www.tei-c.org/ns/1.0'}
                        def get_text(xpath):
                            res = tree.xpath(xpath, namespaces=ns)
                            return res[0].text if res and res[0].text else ""
                        meta['title'] = get_text('//t:titleStmt/t:title')
                        meta['author'] = get_text('//t:titleStmt/t:author')
                        meta['date'] = get_text('//t:titleStmt/t:author/t:date')
                        meta['transcriber'] = get_text('//t:respStmt/t:name')
                        meta['country'] = get_text('//t:msIdentifier/t:country')
                        meta['settlement'] = get_text('//t:msIdentifier/t:settlement')
                        meta['repository'] = get_text('//t:msIdentifier/t:repository')
                        meta['idno'] = get_text('//t:msIdentifier/t:idno')
                        meta['material'] = get_text('//t:support/t:material')
                        meta['objectType'] = get_text('//t:support/t:objectType')
                        hands = _extract_hands_from_tree(tree, ns)
                        meta['hands'] = hands
                        meta['handNote'] = (hands[0].get('description', '') if hands else get_text('//t:handDesc/t:handNote'))
                        meta['language'] = get_text('//t:langUsage/t:p')
                        session['doc_meta'] = meta
                        page = build_page_from_tei(tree, filepath)
                    else:
                        page = build_page_from_pagexml(filepath)
                except Exception as e:
                    return f"Error parsing {uploaded_file.filename}: {e}", 400
            else:
                try:
                    tree = etree.parse(filepath)
                    root = tree.getroot()
                    if 'TEI' in root.tag or 'ns/1.0' in root.tag:
                        session['doc_meta'] = {}
                        page = build_page_from_tei(tree, filepath)
                    else:
                        session['doc_meta'] = session.get('doc_meta') or {}
                        page = build_page_from_pagexml(filepath)
                except Exception as e:
                    return f"Error parsing {uploaded_file.filename}: {e}", 400
            pages.append(page)
        if not pages:
            return render_template('index.html', error='No valid files.')
        session['pages'] = pages
        session['current_page_index'] = 0
        return redirect(url_for('editor'))

    if session.get('pages') and len(session['pages']) > 0:
        return redirect(url_for('editor'))

    return render_template('index.html')

def parse_tei_import(tree):
    """Extract metadata and body content from an existing TEI file for re-editing."""
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    meta = {}
    def get_text(xpath):
        res = tree.xpath(xpath, namespaces=ns)
        return res[0].text if res and res[0].text else ""

    meta['title'] = get_text('//t:titleStmt/t:title')
    meta['author'] = get_text('//t:titleStmt/t:author')
    meta['date'] = get_text('//t:titleStmt/t:author/t:date')
    meta['transcriber'] = get_text('//t:respStmt/t:name')
    meta['country'] = get_text('//t:msIdentifier/t:country')
    meta['settlement'] = get_text('//t:msIdentifier/t:settlement')
    meta['repository'] = get_text('//t:msIdentifier/t:repository')
    meta['idno'] = get_text('//t:msIdentifier/t:idno')
    meta['material'] = get_text('//t:support/t:material')
    meta['objectType'] = get_text('//t:support/t:objectType')
    hands = _extract_hands_from_tree(tree, ns)
    meta['hands'] = hands
    meta['handNote'] = (hands[0].get('description', '') if hands else get_text('//t:handDesc/t:handNote'))
    meta['language'] = get_text('//t:langUsage/t:p')

    session['doc_meta'] = meta

    body = tree.xpath('//t:body/t:div', namespaces=ns)
    if not body:
        body = tree.xpath('//t:body', namespaces=ns)
    lines_data = []
    if body:
        body_xml = etree.tostring(body[0], encoding='unicode')
        body_xml = re.sub(r'^<[^>]+>', '', body_xml)
        body_xml = re.sub(r'</[^>]+>$', '', body_xml)
        raw_lines = re.split(r'<lb[^>]*>', body_xml)
        for i, line_content in enumerate(raw_lines):
            if not line_content.strip():
                continue

            def tag_replacer(match):
                tag = match.group(1)
                attrs = match.group(2)
                content = match.group(3)
                extra_class = ' hand-seg' if tag == 'seg' else ''
                attr_str = ""
                key_vals = re.findall(r'(\w+)="([^"]*)"', attrs)
                for k, v in key_vals:
                    attr_str += f' data-attr-{k}="{v}"'
                return f'<span class="tei-tag tag-{tag}{extra_class}" data-tag="{tag}"{attr_str}>{content}</span>'

            line_content = _collapse_choice_abbr_expan(line_content)
            hand_shift = re.search(r'<handShift\s+new="([^"]*)"\s*/?\s*>', line_content)
            if hand_shift:
                line_content = re.sub(
                    r'<handShift\s+new="([^"]*)"\s*/?\s*>',
                    r'<span class="tei-tag handShift-milestone" data-tag="handShift" data-attr-new="\1" contenteditable="false">¶</span>',
                    line_content,
                )
            html_line = re.sub(r'<(\w+)([^>]*)>(.*?)</\1>', tag_replacer, line_content)
            html_line = html_line.replace('xmlns="http://www.tei-c.org/ns/1.0"', '')
            text_only = re.sub(r'<[^>]+>', '', line_content).strip()
            lines_data.append({
                'id': i,
                'text': text_only,
                'html': html_line.strip(),
                'points': ''
            })
            
        session['imported_lines'] = lines_data

    return redirect(url_for('editor'))

@app.route('/doc_info', methods=['GET'])
def doc_info():
    meta = session.get('doc_meta', {}) or {}
    meta = dict(meta)
    hands = meta.get('hands')
    if not isinstance(hands, list):
        hands = []
    if not hands and meta.get('handNote'):
        hands = [{'description': meta.get('handNote', '')}]
    meta['hands'] = hands
    return render_template('doc_info.html', meta=meta)

@app.route('/save_doc_info', methods=['POST'])
def save_doc_info():
    data = request.form.to_dict()
    hands_raw = data.get('hands')
    if hands_raw:
        try:
            data['hands'] = json.loads(hands_raw)
        except Exception:
            data['hands'] = []
    else:
        data['hands'] = []
    session['doc_meta'] = data
    return redirect(url_for('editor'))

@app.route('/editor/add_hand', methods=['POST'])
def editor_add_hand():
    """Append one hand to session doc_meta; expect JSON body. Returns JSON { hand, hands }."""
    if not session.get('pages'):
        return Response(json.dumps({'error': 'No document'}), status=400, mimetype='application/json')
    meta = session.get('doc_meta') or {}
    meta = dict(meta)
    hands = meta.get('hands')
    if not isinstance(hands, list):
        hands = []
    data = request.get_json(silent=True) or {}
    hand = {
        'xml_id': (data.get('xml_id') or '').strip().lstrip('#') or ('hand-' + str(len(hands) + 1)),
        'scope': (data.get('scope') or '').strip() or None,
        'medium': (data.get('medium') or '').strip() or None,
        'scribe': (data.get('scribe') or '').strip() or None,
        'locus': (data.get('locus') or '').strip() or None,
        'description': (data.get('description') or '').strip() or None,
    }
    if not hand['xml_id']:
        hand['xml_id'] = 'hand-' + str(len(hands) + 1)
    hands = hands + [hand]
    meta['hands'] = hands
    session['doc_meta'] = meta
    return Response(json.dumps({'hand': hand, 'hands': hands}), mimetype='application/json')

@app.route('/editor')
def editor():
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('index'))
    current_index = session.get('current_page_index', 0)
    if current_index < 0 or current_index >= len(pages):
        current_index = 0
        session['current_page_index'] = 0
    page = pages[current_index]
    file_path = page.get('file')
    from_tei_edit = page.get('from_tei_edit')
    if not from_tei_edit and (not file_path or not os.path.exists(file_path)):
        return redirect(url_for('index'))

    lines_in = page.get('lines', [])
    stored_html = page.get('html')
    if stored_html:
        initial_html = stored_html
    else:
        initial_html = None

    tags = load_tags()
    meta = session.get('doc_meta') or {}
    hands = meta.get('hands') or []
    hand_ids = ['#' + (h.get('xml_id') or '').strip().lstrip('#') for h in hands if (h.get('xml_id') or '').strip()]
    page_name = os.path.basename(file_path) if file_path else ""
    highlight_gram = request.args.get('highlight')
    page_labels = [os.path.basename(p.get('file', '')) or ('Page ' + str(i + 1)) for i, p in enumerate(pages)]
    pages_summary = [{'label': page_labels[i], 'line_count': len(p.get('lines', []))} for i, p in enumerate(pages)]
    page_image_urls = [p.get('img_url') or '' for p in pages]
    return render_template('editor.html',
                           lines=lines_in,
                           img_url=page.get('img_url', ''),
                           orig_width=page.get('orig_width', 0),
                           orig_height=page.get('orig_height', 0),
                           tags=tags,
                           hand_ids=hand_ids,
                           hands=hands,
                           page_name=page_name,
                           line_count=len(lines_in),
                           image_src=page.get('image_src', ''),
                           initial_html=initial_html,
                           current_page_index=current_index,
                           total_pages=len(pages),
                           highlight_gram=highlight_gram,
                           import_type=page.get('import_type', 'transkribus'),
                           page_labels=page_labels,
                           pages_summary=pages_summary,
                           page_image_urls=page_image_urls)


@app.route('/editor/save_page', methods=['POST'])
def editor_save_page():
    """Save current page HTML to session (for auto-save and before leaving the page). Accepts JSON or form body."""
    pages = session.get('pages')
    if not pages:
        return Response(json.dumps({'ok': False, 'error': 'no pages'}), status=400, mimetype='application/json')
    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json(silent=True) or {}
        html_content = data.get('html_content', '')
        try:
            current_index = int(data.get('current_page_index', session.get('current_page_index', 0)))
        except (TypeError, ValueError):
            current_index = session.get('current_page_index', 0)
    else:
        html_content = request.form.get('html_content', '')
        try:
            current_index = int(request.form.get('current_page_index', session.get('current_page_index', 0)))
        except (TypeError, ValueError):
            current_index = session.get('current_page_index', 0)
    if 0 <= current_index < len(pages):
        session['pages'][current_index]['html'] = html_content
    return Response(json.dumps({'ok': True}), mimetype='application/json')


@app.route('/editor/switch_page', methods=['POST'])
def switch_page():
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('index'))
    # Use form's current_page_index so we save HTML to the page the client is actually showing (avoids session/display mismatch)
    current_index = request.form.get('current_page_index', type=int)
    if current_index is None or current_index < 0 or current_index >= len(pages):
        current_index = session.get('current_page_index', 0)
    target_index = request.form.get('target_page_index', type=int)
    if target_index is not None and 0 <= target_index < len(pages):
        html_content = request.form.get('html_content', '')
        if 0 <= current_index < len(pages):
            session['pages'][current_index]['html'] = html_content
        session['current_page_index'] = target_index
    highlight_gram = request.form.get('highlight_gram') or request.args.get('highlight')
    keep_ligatures = request.form.get('keep_ligatures')
    url = url_for('editor')
    if highlight_gram:
        url = url_for('editor', highlight=highlight_gram)
    if keep_ligatures:
        url = url + ('&' if '?' in url else '?') + 'ligatures=1'
    return redirect(url)


@app.route('/editor/change_image', methods=['POST'])
@limiter.limit(_rate_upload)
def change_image():
    """Replace the image for the current page with an uploaded image file."""
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('index'))
    # Prefer the form's current_page_index so we update the page the client is actually showing
    current_index = request.form.get('current_page_index', type=int)
    if current_index is None or current_index < 0 or current_index >= len(pages):
        current_index = session.get('current_page_index', 0)
        if current_index is None or current_index < 0 or current_index >= len(pages):
            return redirect(url_for('editor'))
    f = request.files.get('image')
    if not f or not f.filename:
        return redirect(url_for('editor'))
    ext = os.path.splitext(f.filename)[-1].lower() or '.png'
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif'):
        return redirect(url_for('editor'))
    filename = f"{uuid.uuid4()}_{f.filename}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    f.save(filepath)
    orig_w, orig_h = 0, 0
    try:
        from PIL import Image
        with Image.open(filepath) as im:
            orig_w, orig_h = im.size[0], im.size[1]
    except Exception:
        pass
    img_url = url_for('send_upload', filename=filename)
    page = session['pages'][current_index]
    page['img_url'] = img_url
    page['orig_width'] = orig_w
    page['orig_height'] = orig_h
    page['image_src'] = ''
    if page.get('import_type') == 'image':
        page['file'] = filepath
    return redirect(url_for('editor'))


@app.route('/editor/reorder_pages', methods=['POST'])
def reorder_pages():
    """Apply new page order; order is comma-separated indices e.g. 0,2,1,3. Saves current page HTML first."""
    pages = session.get('pages')
    if not pages or len(pages) < 2:
        return redirect(url_for('editor'))
    current_index = request.form.get('current_page_index', type=int)
    if current_index is None or current_index < 0 or current_index >= len(pages):
        current_index = session.get('current_page_index', 0)
    html_content = request.form.get('html_content', '')
    if html_content and 0 <= current_index < len(pages):
        session['pages'][current_index]['html'] = html_content
    order_str = request.form.get('order')
    if not order_str:
        return redirect(url_for('editor'))
    try:
        new_order = [int(x.strip()) for x in order_str.split(',') if x.strip()]
    except ValueError:
        return redirect(url_for('editor'))
    if set(new_order) != set(range(len(pages))) or len(new_order) != len(pages):
        return redirect(url_for('editor'))
    reordered = [pages[i] for i in new_order]
    old_page = pages[current_index]
    new_index = reordered.index(old_page)
    session['pages'] = reordered
    session['current_page_index'] = new_index
    return redirect(url_for('editor'))


@app.route('/editor/add_pages', methods=['POST'])
@limiter.limit(_rate_upload)
def add_pages():
    """Append new page(s) from uploaded file(s). Saves current page HTML first."""
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('index'))
    current_index = request.form.get('current_page_index', type=int)
    if current_index is None or current_index < 0 or current_index >= len(pages):
        current_index = session.get('current_page_index', 0)
    html_content = request.form.get('html_content', '')
    if current_index < len(pages):
        session['pages'][current_index]['html'] = html_content
    uploaded = request.files.getlist('file')
    for f in uploaded:
        if not f or not f.filename:
            continue
        filename = f"{uuid.uuid4()}_{f.filename}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        f.save(filepath)
        ext = os.path.splitext(f.filename)[-1].lower()
        if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif'):
            new_page = build_page_from_image(filepath)
        else:
            try:
                tree = etree.parse(filepath)
                root = tree.getroot()
                if 'TEI' in root.tag or 'ns/1.0' in root.tag:
                    new_page = build_page_from_tei(tree, filepath)
                else:
                    new_page = build_page_from_pagexml(filepath)
            except Exception:
                continue
        session['pages'].append(new_page)
    return redirect(url_for('editor'))


@app.route('/editor/remove_pages', methods=['POST'])
def remove_pages():
    """Remove pages at given indices (comma-separated). Saves current page HTML first."""
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('editor'))
    current_index = request.form.get('current_page_index', type=int)
    if current_index is None or current_index < 0 or current_index >= len(pages):
        current_index = session.get('current_page_index', 0)
    html_content = request.form.get('html_content', '')
    if current_index < len(pages):
        session['pages'][current_index]['html'] = html_content
    indices_str = request.form.get('indices', '')
    try:
        to_remove = sorted(set(int(x.strip()) for x in indices_str.split(',') if x.strip()), reverse=True)
    except ValueError:
        return redirect(url_for('editor'))
    if not to_remove:
        return redirect(url_for('editor'))
    for i in to_remove:
        if 0 <= i < len(session['pages']):
            session['pages'].pop(i)
            if current_index == i:
                current_index = max(0, min(current_index, len(session['pages']) - 1))
            elif current_index > i:
                current_index -= 1
    session['current_page_index'] = current_index
    if not session['pages']:
        return redirect(url_for('index'))
    return redirect(url_for('editor'))


def _page_line_texts(page):
    """Return list of plain-text strings, one per line, for a page (from stored html or lines)."""
    html = page.get('html')
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        return [div.get_text(strip=True) for div in soup.find_all(class_='line-wrapper')]
    lines = page.get('lines', [])
    return [line.get('text', '') for line in lines]


@app.route('/api/ligature_lines', methods=['GET', 'POST'])
def api_ligature_lines():
    """Return line texts for all pages (for ligature analysis across pages). POST may include html_content and current_page_index to save current page first."""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        html_content = data.get('html_content')
        try:
            current_index = int(data.get('current_page_index', session.get('current_page_index', 0)))
        except (TypeError, ValueError):
            current_index = session.get('current_page_index', 0)
        pages = session.get('pages', [])
        if html_content is not None and 0 <= current_index < len(pages):
            session['pages'][current_index]['html'] = html_content
    pages = session.get('pages', [])
    lines_by_page = [_page_line_texts(p) for p in pages]
    return Response(json.dumps({'linesByPage': lines_by_page}), mimetype='application/json')


@app.route('/proxy_image')
def proxy_image():
    """Proxy external image URLs (e.g. Transkribus) to avoid CORS when loading in the editor."""
    url = request.args.get('url')
    if not url:
        return Response('Missing url parameter', status=400)
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return Response('Invalid URL scheme', status=400)
    try:
        req = Request(url, headers={'User-Agent': 'TEI-Helper/1.0'})
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
            content_type = resp.headers.get('Content-Type', 'image/jpeg')
    except Exception as e:
        return Response(f'Proxy error: {e}', status=502)
    return Response(data, mimetype=content_type)

@app.route('/close')
def close_file():
    session.pop('current_file', None)
    session.pop('doc_meta', None)
    session.pop('imported_lines', None)
    session.pop('pages', None)
    session.pop('current_page_index', None)
    return redirect(url_for('index'))


@app.route('/terms')
def terms():
    """Terms of use page (local app)."""
    import base64
    contact = os.environ.get('PRIVACY_CONTACT_EMAIL', '').strip()
    contact_encoded = ''
    if contact and '@' in contact:
        try:
            local, _, domain = contact.rpartition('@')
            contact_encoded = base64.b64encode(
                (local + '\0' + domain).encode('utf-8')
            ).decode('ascii')
        except Exception:
            contact_encoded = ''
    return render_template(
        'terms.html',
        contact_email=contact,
        contact_encoded=contact_encoded,
    )


@app.route('/privacy')
def privacy():
    """Redirect legacy privacy URL to terms."""
    return redirect(url_for('terms'))


@app.route('/tags', methods=['GET', 'POST'])
def tag_manager():
    current_tags = load_tags()
    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action in ['add', 'edit']:
            attr_names = request.form.getlist('attr_name[]')
            attr_labels = request.form.getlist('attr_label[]')
            attr_descs = request.form.getlist('attr_desc[]')
            attr_list = []
            for i in range(len(attr_names)):
                if attr_names[i].strip():
                    attr_list.append({
                        "name": attr_names[i].strip(),
                        "label": (attr_labels[i].strip() if i < len(attr_labels) else "") or attr_names[i].capitalize(),
                        "desc": attr_descs[i].strip() if i < len(attr_descs) else "",
                        "suggestions": []
                    })
            code = (request.form.get('code') or '').strip()
            if not code:
                return redirect(url_for('tag_manager'))
            tag_data = {
                "code": code,
                "label": (request.form.get('label') or '').strip() or code,
                "category": (request.form.get('category') or '').strip() or 'visual',
                "color": (request.form.get('color') or '').strip() or '#E1BEE7',
                "description": (request.form.get('description') or '').strip(),
                "attrs": attr_list
            }
            if action == 'add':
                existing = next((idx for idx, t in enumerate(current_tags) if t.get('code') == code), None)
                if existing is not None:
                    current_tags[existing] = tag_data
                else:
                    current_tags.append(tag_data)
            elif action == 'edit':
                original_code = (request.form.get('original_code') or '').strip()
                lookup_code = original_code if original_code else code
                for idx, t in enumerate(current_tags):
                    if t.get('code') == lookup_code:
                        current_tags[idx] = tag_data
                        break
            save_tags(current_tags)
        elif action == 'delete':
            code = (request.form.get('code') or '').strip()
            current_tags = [t for t in current_tags if t['code'] != code]
            save_tags(current_tags)
        return redirect(url_for('tag_manager'))
    return render_template('tags.html', tags=current_tags)

@app.route('/export_layout', methods=['GET', 'POST'])
def export_layout():
    """View or edit the TEI layout template used for export. Placeholders: {title}, {author}, {date}, {transcriber}, {country}, {settlement}, {repository}, {idno}, {material}, {objectType}, {handDesc}, {language}. The body must contain an empty <div type="edition"> inside <text><body>. Hand descriptions are built from Document Information (handDesc/handNote)."""
    if request.method == 'POST':
        content = request.form.get('layout_content', '')
        if content.strip():
            try:
                to_save = _indent_xml_string(content)
                with open(TEI_LAYOUT_FILE, 'w', encoding='utf-8') as f:
                    f.write(to_save)
                return redirect(url_for('export_layout'))
            except Exception as e:
                raw = _indent_xml_string(get_tei_template())
                return render_template('export_layout.html', layout_content=_safe_layout_display(raw), error=str(e))
        return redirect(url_for('export_layout'))
    raw = _indent_xml_string(get_tei_template())
    return render_template('export_layout.html', layout_content=_safe_layout_display(raw), error=None)

@app.route('/export_layout_reset', methods=['POST'])
def export_layout_reset():
    """Reset TEI layout to the built-in default."""
    try:
        if os.path.isfile(TEI_LAYOUT_FILE):
            os.remove(TEI_LAYOUT_FILE)
    except Exception:
        pass
    return redirect(url_for('export_layout'))

TEI_NS = 'http://www.tei-c.org/ns/1.0'


def _xml_escape_text(s):
    if not s:
        return s
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _get_data_attrs(span):
    """Extract data-attr-* as dict; keys lowercased so expan/Expan both work after HTML lowercasing."""
    return {k.replace('data-attr-', '').lower(): str(v) for k, v in (getattr(span, 'attrs', {}) or {}).items()
            if k and str(k).lower().startswith('data-attr-') and v is not None}

def _line_plain_text_and_ranges(line_div):
    """Walk line_div in document order; return (plain_text, ranges).
    ranges: list of (start, end, kind, tag_name, attrs) with kind in ('tag','handShift','hi').
    handShift is (pos, pos, 'handShift', None, attrs). No text duplication."""
    parts = []
    def walk(parent):
        for child in parent.children:
            if isinstance(child, str):
                parts.append(('text', str(child)))
            elif getattr(child, 'name', None) == 'span':
                classes = child.get('class', [])
                if 'tei-tag' in classes:
                    tag = child.get('data-tag')
                    if not tag:
                        walk(child)
                        continue
                    text = child.get_text()
                    attrs = _get_data_attrs(child)
                    if tag == 'handShift':
                        parts.append(('handShift', text, attrs))
                    else:
                        parts.append(('tag', text, tag, attrs))
                elif 'ligature-mark' in classes:
                    parts.append(('hi', child.get_text(), child.get('data-ngram')))
                else:
                    walk(child)
            else:
                walk(child)
    walk(line_div)
    plain_parts = []
    offset = 0
    ranges = []
    for p in parts:
        if p[0] == 'text':
            plain_parts.append(p[1])
            offset += len(p[1])
        elif p[0] == 'handShift':
            pos = offset
            plain_parts.append(p[1])
            offset += len(p[1])
            ranges.append((pos, pos, 'handShift', None, p[2]))
        elif p[0] == 'tag':
            start = offset
            plain_parts.append(p[1])
            length = len(p[1])
            offset += length
            ranges.append((start, offset, 'tag', p[2], p[3]))
        elif p[0] == 'hi':
            start = offset
            plain_parts.append(p[1])
            length = len(p[1])
            offset += length
            hi_attrs = {'rend': 'ligature'}
            if p[2]:
                hi_attrs['n'] = p[2]
            ranges.append((start, offset, 'tag', 'hi', hi_attrs))
    plain_text = ''.join(plain_parts)
    return plain_text, ranges

def _normalize_hand_attr(attrs):
    """Ensure hand/new attributes have # prefix for TEI."""
    if not attrs:
        return attrs
    a = dict(attrs)
    for key in ('hand', 'new'):
        if key in a and a[key] and not str(a[key]).startswith('#'):
            a[key] = '#' + str(a[key])
    return a

def _event_order_key(e):
    """Order at same boundary: close abbr first, then expan_inline (so expan is added to choice), then close choice, then other close, then open, then handShift."""
    ev_type, tag = e[1], (e[2] or '')
    if ev_type == 'close':
        if tag == 'abbr':
            return (0, 0)
        if tag == 'choice':
            return (0, 2)
        return (0, 0)
    if ev_type == 'expan_inline':
        return (0, 1)
    if ev_type == 'open':
        return (2, 0 if tag == 'choice' else 1)
    if ev_type == 'handShift':
        return (3, 0)
    return (4, 0)


def _ranges_to_inline_segments(line_text, ranges):
    """Convert (line_text, ranges) to a list of segments: ('text', s) or ('open', tag, attrs) or ('close', tag) or ('handShift', attrs) or ('expan_inline', value).
    choice+expan produces <choice><abbr>...</abbr><expan>...</expan></choice>. Overlapping ranges are nested (close before open at same position)."""
    if not ranges:
        return [('text', line_text)] if line_text else []
    boundaries = sorted(set([0, len(line_text)] + [r[0] for r in ranges] + [r[1] for r in ranges]))
    events = []
    for start, end, kind, tag_name, attrs in ranges:
        if kind == 'handShift':
            events.append((start, 'handShift', None, attrs))
        elif kind == 'tag' and tag_name == 'choice':
            # TEI <choice><abbr>text</abbr><expan>expansion</expan></choice>; always emit expan (use value or '')
            a = attrs or {}
            expan_val = a.get('expan') or a.get('expansion') or ''
            events.append((start, 'open', 'choice', {}))
            events.append((start, 'open', 'abbr', {}))
            events.append((end, 'close', 'abbr', None))
            events.append((end, 'expan_inline', expan_val, None))
            events.append((end, 'close', 'choice', None))
        else:
            events.append((start, 'open', tag_name, attrs or {}))
            events.append((end, 'close', tag_name, None))
    def _open_sort_key(tag):
        return (0 if tag == 'choice' else 1, tag or '')
    events.sort(key=lambda e: (e[0], _event_order_key(e), _open_sort_key(e[2]) if e[1] == 'open' else (e[2] or '')))
    segments = []
    open_stack = []
    for i in range(len(boundaries) - 1):
        b, next_b = boundaries[i], boundaries[i + 1]
        text_run = line_text[b:next_b]
        events_at_b = [e for e in events if e[0] == b]
        for ev in events_at_b:
            if ev[1] == 'close':
                if open_stack:
                    segments.append(('close', open_stack.pop()[0]))
            elif ev[1] == 'expan_inline':
                segments.append(('expan_inline', ev[2] or ''))
            elif ev[1] == 'open':
                tag, attrs = ev[2], _normalize_hand_attr(ev[3]) or {}
                segments.append(('open', tag, attrs))
                open_stack.append((tag, attrs))
            elif ev[1] == 'handShift':
                segments.append(('handShift', _normalize_hand_attr(ev[3]) or {}))
        if text_run:
            segments.append(('text', text_run))
    return segments

def _apply_segments_to_tei(segments, ns, tei_div, lb):
    """Apply segment list to tei_div: set lb.tail and append top-level elements with correct .text/.tail. No text duplication.
    choice: <choice><abbr>marked text</abbr><expan>expansion</expan></choice>."""
    lb_tail = []
    last_toplevel = None
    stack = []

    def append_text(s):
        esc = _xml_escape_text(s)
        if not esc:
            return
        if stack:
            parent = stack[-1]
            if len(parent) == 0:
                parent.text = (parent.text or '') + esc
            else:
                parent[-1].tail = (parent[-1].tail or '') + esc
        else:
            if last_toplevel is None:
                lb_tail.append(esc)
            else:
                last_toplevel.tail = (last_toplevel.tail or '') + esc

    for seg in segments:
        if seg[0] == 'text':
            append_text(seg[1])
        elif seg[0] == 'open':
            tag_name, attrs = seg[1], seg[2]
            elem = etree.Element(f'{{{ns}}}{tag_name}')
            for k, v in (attrs or {}).items():
                if v is not None:
                    elem.set(k, str(v))
            if stack:
                stack[-1].append(elem)
            else:
                tei_div.append(elem)
                last_toplevel = elem
            stack.append(elem)
        elif seg[0] == 'close':
            if stack:
                stack.pop()
                if not stack:
                    last_toplevel = tei_div[-1] if len(tei_div) > 0 else None
        elif seg[0] == 'handShift':
            attrs = seg[1] or {}
            elem = etree.Element(f'{{{ns}}}handShift')
            for k, v in attrs.items():
                if k and v is not None:
                    elem.set(k, str(v))
            if stack:
                stack[-1].append(elem)
            else:
                tei_div.append(elem)
                last_toplevel = elem
        elif seg[0] == 'expan_inline':
            value = (seg[1] or '').strip()
            if stack:
                expan_el = etree.Element(f'{{{ns}}}expan')
                if value:
                    expan_el.text = _xml_escape_text(value)
                stack[-1].append(expan_el)
    lb.tail = ''.join(lb_tail) if lb_tail else None


def _merge_consecutive_seg_hands(tei_div, ns):
    """Merge consecutive <seg hand="X">...</seg><lb/><seg hand="X">...</seg> into a single <seg hand="X">...<lb/>...</seg> (standard TEI: one seg wrapping multi-line selection with lb inside)."""
    seg_tag = f'{{{ns}}}seg'
    lb_tag = f'{{{ns}}}lb'
    children = list(tei_div)
    i = 0
    while i < len(children):
        elem = children[i]
        if elem.tag != seg_tag:
            i += 1
            continue
        hand = elem.get('hand')
        if not hand:
            i += 1
            continue
        run = [elem]
        j = i + 1
        while j + 1 < len(children) and children[j].tag == lb_tag and children[j + 1].tag == seg_tag and children[j + 1].get('hand') == hand:
            run.append(children[j])
            run.append(children[j + 1])
            j += 2
        if len(run) == 1:
            i += 1
            continue
        segs = run[0::2]
        lbs = run[1::2]
        new_seg = etree.Element(seg_tag, hand=hand)
        for k in range(len(segs)):
            seg = segs[k]
            if k == 0 and seg.text:
                new_seg.text = (new_seg.text or '') + (seg.text or '')
            for c in seg:
                new_seg.append(deepcopy(c))
            if k < len(lbs):
                lb = lbs[k]
                new_seg.append(lb)
                lb.tail = (segs[k + 1].text or '') if k + 1 < len(segs) else ''
        idx = tei_div.index(run[0])
        tei_div.insert(idx, new_seg)
        for seg in segs:
            tei_div.remove(seg)
        children = list(tei_div)
        i = idx + 1
    return tei_div


def _append_page_html_to_tei(tei_div, page_html, page_num, include_facs):
    """Append <pb n="page_num"/> and line content from page_html. Uses offset-based inline serialization: no text duplication, tags wrap slices of the single line string."""
    if isinstance(page_html, str):
        soup = BeautifulSoup(page_html, 'html.parser')
    else:
        soup = page_html
    ns = TEI_NS
    pb = etree.Element(f'{{{ns}}}pb')
    pb.set('n', str(page_num))
    tei_div.append(pb)
    for line_div in soup.find_all(class_='line-wrapper'):
        points = line_div.get('data-points', '')
        lb = etree.Element(f'{{{ns}}}lb')
        if include_facs and points:
            lb.set('facs', points)
        tei_div.append(lb)
        plain_text, ranges = _line_plain_text_and_ranges(line_div)
        segments = _ranges_to_inline_segments(plain_text, ranges)
        _apply_segments_to_tei(segments, ns, tei_div, lb)


@app.route('/export', methods=['POST'])
def export_tei():
    try:
        current_page_index = request.form.get('current_page_index', type=int)
        if current_page_index is not None:
            pages = session.get('pages', [])
            if pages and 0 <= current_page_index < len(pages):
                session['pages'][current_page_index]['html'] = request.form.get('html_content', '')
        html_content = request.form.get('html_content', '')
        export_format = request.form.get('export_format', 'positional')
        pages = session.get('pages', []) or []
        include_facs = export_format == 'positional'

        meta = session.get('doc_meta', {}) or {}
        defaults = {k: "???" for k in ['title','author','date','transcriber','country','settlement',
                                       'repository','idno','material','objectType','language']}
        defaults.update((k, v) for k, v in meta.items() if k not in ('hands', 'handNote'))
        hands = meta.get('hands')
        if isinstance(hands, str):
            try:
                hands = json.loads(hands)
            except Exception:
                hands = []
        if not isinstance(hands, list):
            hands = []
        hands = [h for h in hands if isinstance(h, dict)]
        defaults['handNote'] = (hands[0].get('description', '') if hands else meta.get('handNote', ''))

        try:
            hand_desc_el = build_hand_desc_element(hands, meta.get('handNote', ''))
        except Exception:
            hand_desc_el = etree.Element(f'{{{TEI_NS}}}handDesc')
        tei_root = _build_tei_root_element(defaults, hand_desc_el)
        tei_div = tei_root.find(".//{http://www.tei-c.org/ns/1.0}div[@type='edition']")
        if tei_div is None:
            return Response("Export failed: could not find edition div.", status=500, mimetype='text/plain')

        if not pages:
            soup = BeautifulSoup(html_content or '', 'html.parser')
            _append_page_html_to_tei(tei_div, soup, 1, include_facs)
        else:
            for i, page in enumerate(pages):
                page_html = page.get('html') if isinstance(page, dict) else None
                if page_html:
                    _append_page_html_to_tei(tei_div, page_html, i + 1, include_facs)
                else:
                    lines = page.get('lines', []) if isinstance(page, dict) else []
                    buf = []
                    for line in lines:
                        pts = line.get('points', '') if isinstance(line, dict) else ''
                        html_part = (line.get('html') or line.get('text', '')) if isinstance(line, dict) else ''
                        buf.append(f'<div class="line-wrapper" data-points="{escape(pts)}">{html_part}</div>')
                    _append_page_html_to_tei(tei_div, ''.join(buf), i + 1, include_facs)

        _merge_consecutive_seg_hands(tei_div, TEI_NS)

        out_xml = etree.tostring(tei_root, pretty_print=True, xml_declaration=True, encoding='UTF-8')
        filename = 'annotated_tei_clean.xml' if export_format == 'clean' else 'annotated_tei.xml'
        return Response(out_xml, mimetype="application/xml",
                        headers={"Content-disposition": f"attachment; filename={filename}"})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response(f"Export failed: {e}", status=500, mimetype='text/plain')


def _page_to_tei_edit_serializable(page):
    """Convert a session page dict to a JSON-serializable dict for TEI-edit file (no server paths, base64 for local images)."""
    import base64
    out = {
        'lines': page.get('lines', []),
        'html': page.get('html'),
        'orig_width': page.get('orig_width', 0),
        'orig_height': page.get('orig_height', 0),
        'import_type': page.get('import_type', 'transkribus'),
    }
    image_src = (page.get('image_src') or '').strip()
    filepath = page.get('file')
    # Local image: stored in UPLOAD_FOLDER (image-only import or replaced image)
    image_ext = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif')
    if filepath and os.path.isfile(filepath) and filepath.lower().endswith(image_ext):
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            out['image_data_base64'] = base64.b64encode(data).decode('ascii')
            out['image_filename'] = os.path.basename(filepath)
            out['image_src'] = ''
        except Exception:
            out['image_src'] = image_src
            out['image_data_base64'] = None
    else:
        out['image_src'] = image_src
        out['image_data_base64'] = None
    return out


@app.route('/editor/save_tei_edit_file', methods=['POST'])
def save_tei_edit_file():
    """Save full edit state (all pages, tags, images) as a TEI-edit file for loading later."""
    pages = session.get('pages')
    if not pages:
        return Response(json.dumps({'error': 'No document'}), status=400, mimetype='application/json')
    # Persist current page HTML from request
    if request.content_type and 'application/json' in (request.content_type or ''):
        data = request.get_json(silent=True) or {}
        html_content = data.get('html_content', '')
        try:
            current_index = int(data.get('current_page_index', session.get('current_page_index', 0)))
        except (TypeError, ValueError):
            current_index = session.get('current_page_index', 0)
    else:
        html_content = request.form.get('html_content', '')
        try:
            current_index = int(request.form.get('current_page_index', session.get('current_page_index', 0)))
        except (TypeError, ValueError):
            current_index = session.get('current_page_index', 0)
    if 0 <= current_index < len(pages):
        session['pages'][current_index]['html'] = html_content

    payload = {
        'version': 1,
        'doc_meta': session.get('doc_meta') or {},
        'current_page_index': session.get('current_page_index', 0),
        'pages': [_page_to_tei_edit_serializable(p) for p in pages],
    }
    # Ensure doc_meta values are JSON-serializable (hands etc.)
    doc_meta = payload['doc_meta']
    if isinstance(doc_meta.get('hands'), list):
        doc_meta = dict(doc_meta)
        payload['doc_meta'] = doc_meta
    json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    filename = 'project.tei-edit'
    return Response(
        json_bytes,
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@app.route('/load_tei_edit', methods=['POST'])
@limiter.limit(_rate_upload)
def load_tei_edit():
    """Load a previously saved TEI-edit file and restore session (pages, doc_meta, images)."""
    import base64
    f = request.files.get('file')
    if not f or not f.filename:
        return render_template('index.html', error='Please select a TEI-edit file.')
    try:
        raw = f.read()
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        data = json.loads(raw)
    except Exception as e:
        return render_template('index.html', error=f'Invalid TEI-edit file: {e}')
    if not isinstance(data.get('pages'), list) or not data['pages']:
        return render_template('index.html', error='TEI-edit file has no pages.')
    version = data.get('version', 0)
    doc_meta = data.get('doc_meta') or {}
    current_page_index = min(max(0, int(data.get('current_page_index', 0))), len(data['pages']) - 1)
    restored_pages = []
    for p in data['pages']:
        page = {
            'lines': p.get('lines', []),
            'html': p.get('html'),
            'orig_width': int(p.get('orig_width', 0)) or 0,
            'orig_height': int(p.get('orig_height', 0)) or 0,
            'import_type': p.get('import_type', 'transkribus'),
            'image_src': (p.get('image_src') or '').strip(),
            'from_tei_edit': True,
        }
        image_b64 = p.get('image_data_base64')
        if image_b64:
            try:
                img_data = base64.b64decode(image_b64)
                ext = '.png'
                orig_name = p.get('image_filename') or 'image'
                if orig_name.lower().endswith(('.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif')):
                    ext = os.path.splitext(orig_name)[1].lower()
                filename = f"{uuid.uuid4()}_restored{ext}"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                with open(filepath, 'wb') as out:
                    out.write(img_data)
                page['file'] = filepath
                page['img_url'] = url_for('send_upload', filename=filename)
                page['image_src'] = ''
            except Exception:
                # Fallback: no image
                page['file'] = None
                page['img_url'] = ''
        else:
            image_src = page['image_src']
            if image_src and (image_src.startswith('http://') or image_src.startswith('https://')):
                page['img_url'] = url_for('proxy_image', url=image_src)
            else:
                page['img_url'] = ''
            # Placeholder file so editor() has a path (optional but keeps logic simple)
            placeholder = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}_tei_edit_placeholder.xml")
            with open(placeholder, 'w', encoding='utf-8') as out:
                out.write('<?xml version="1.0"?><placeholder/>')
            page['file'] = placeholder
        restored_pages.append(page)
    session['doc_meta'] = doc_meta
    session['pages'] = restored_pages
    session['current_page_index'] = current_page_index
    return redirect(url_for('editor'))


if __name__ == '__main__':
    import flaskwebgui
    flaskwebgui.FlaskUI(app=app, server="flask").run()